import re

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app.logging_config import configure_logging
configure_logging()

from app.models import (
    AnalyzeRoleRequest,
    AnalyzeRoleResponse,
    GenerateCareerPlanRequest,
    GenerateCareerPlanResponse,
    GenerateRoadmapRequest,
    GenerateRoadmapResponse,
    MasteryLevelItem,
    MarketRefreshResponse,
    MissingSkill,
    ProfileAnalysisResponse,
    GetResourcesRequest,
    GetResourcesResponse,
    GitHubRepo,
    LearningResource,
    SkillImpactRequest,
    SkillImpactResponse,
    SkillImpactScoreItem,
    SubmitTaskRequest,
    SubmitTaskResponse,
    UserMasteryResponse,
    VerifyChallengeRequest,
    VerifyChallengeResponse,
    VerifyAnswerRequest,
    VerifyAnswerResponse,
)
from app.services.profile_engine import analyze_profile
from app.services.roadmap_engine import generate_roadmap
from app.services.role_engine import analyze_role
from app.services.eval_engine import evaluate_submission
from app.services.utils import load_user_metrics, update_metrics_on_task_submission
from app.services.agent_orchestrator import run_skill_gap_pipeline
from app.services import skill_impact_engine
from app.services import embedding_service
from app.services import resources_engine
from app.services import market_service
from app.services import mastery_tracker
from app.services import s3_service
from app.agents import verification_agent
from app.services import user_store

app = FastAPI(title="CareerOS")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/metrics/{user_id}")
def get_metrics(user_id: str):
    metrics = load_user_metrics(user_id)
    # Merge DynamoDB fields into the metrics response
    try:
        db_user = user_store.get_user(user_id) or {}
        metrics.learned_skills = db_user.get("learned_skills") or user_store.get_learned_skills(user_id)
        # Surface the next priority skill computed by the agentic re-ranking loop
        metrics.next_priority_skill = db_user.get("next_priority_skill")
    except Exception:
        pass  # non-fatal — base metrics still returned
    return metrics


def _auto_quality_score(submission_text: str) -> int:
    words = submission_text.strip().split()
    word_count = len(words)
    if word_count < 30:
        score = 40
    elif word_count <= 80:
        score = 65
    else:
        score = 85

    code_like_pattern = re.compile(
        r"[;{}]|\b(def|class|return|import|for|while|if|else|elif)\b|=>|\bconst\b|\bfunction\b"
    )
    if code_like_pattern.search(submission_text):
        score += 10

    return min(score, 100)


@app.post("/submit-task", response_model=SubmitTaskResponse)
def submit_task(payload: SubmitTaskRequest) -> SubmitTaskResponse:
    import logging as _logging
    _log = _logging.getLogger(__name__)

    # ── 1. Evaluate submission via LLM ────────────────────────────────────────
    feedback = evaluate_submission(
        submission_text=payload.submission_text,
        user_id=payload.user_id,
        skill=payload.skill,
    )
    quality_score = feedback.rating

    # ── 2. Update XP / streak / level ────────────────────────────────────────
    updated = update_metrics_on_task_submission(
        payload.user_id,
        quality_score=quality_score,
    )

    # ── 2b. Persist the practised skill so the user's history is remembered ──
    if payload.skill and quality_score >= 40:
        try:
            user_store.add_learned_skill(payload.user_id, payload.skill)
            # Also bump per-skill XP (proportional to rating)
            user_store.update_skill_xp(payload.user_id, payload.skill, max(1, quality_score // 10))
        except Exception as exc:
            _log.warning("add_learned_skill failed (non-fatal): %s", exc)

    # ── 3. Closed-loop re-ranking: determine next priority skill ─────────────
    next_priority_skill: str | None = None
    try:
        # Resolve target_role and user_skills from payload or stored profile
        db_user     = user_store.get_user(payload.user_id) or {}
        target_role = payload.target_role or db_user.get("target_role", "")
        user_skills = payload.user_skills or db_user.get("user_skills") or []

        if target_role:
            # Persist updated profile if new info arrived from the frontend
            if payload.target_role or payload.user_skills:
                user_store.update_user_profile(
                    payload.user_id,
                    target_role,
                    user_skills,
                )

            # Get mastery data for discount calculation
            verified = set(db_user.get("verified_skills", []))
            xp_map   = user_store.get_skill_xp_map(payload.user_id)

            # Compute keyword-based impact scores
            ranked = skill_impact_engine.compute_impact_scores(
                user_skills=user_skills,
                target_role=target_role,
                verified_skills=verified,
                skill_xp_map=xp_map,
            )

            # Extract gap skills (user doesn't have them yet)
            user_skills_lower = {s.lower() for s in user_skills}
            gap_skills  = [r["skill"] for r in ranked if r["skill"].lower() not in user_skills_lower]

            if gap_skills:
                # Blend with semantic embeddings for richer re-ranking signal
                base_scores = {r["skill"]: r["impact_score"] for r in ranked}
                reranked    = embedding_service.rerank_skills_with_embeddings(
                    skills=gap_skills[:20],   # cap to avoid excessive Bedrock calls
                    role=target_role,
                    base_scores=base_scores,
                )
                next_priority_skill = reranked[0]["skill"] if reranked else gap_skills[0]
            elif ranked:
                # All skills known — surface the lowest-mastery one
                next_priority_skill = ranked[-1]["skill"]

            if next_priority_skill:
                user_store.set_next_priority_skill(payload.user_id, next_priority_skill)
                _log.info(
                    "Re-rank complete: user='%s' role='%s' next='%s'",
                    payload.user_id, target_role, next_priority_skill,
                )
    except Exception as exc:
        _log.warning("Re-ranking failed (non-fatal): %s", exc)

    # ── 4. Return enriched response ───────────────────────────────────────────
    return SubmitTaskResponse(
        xp=updated.xp,
        level=updated.level,
        rank=updated.rank,
        streak=updated.streak,
        execution_score=updated.execution_score,
        feedback=feedback,
        next_priority_skill=next_priority_skill,
    )


@app.post("/analyze-profile", response_model=ProfileAnalysisResponse)
def analyze_profile_endpoint(
    resume: UploadFile | None = File(None),
    github_username: str | None = Form(None),
    user_id: str | None = Form(None),
) -> ProfileAnalysisResponse:
    import logging as _logging
    _log = _logging.getLogger(__name__)

    resume_bytes: bytes | None = None
    if resume:
        resume_bytes = resume.file.read()
        # Store resume in S3 (best-effort — don't fail the request if S3 is unavailable)
        try:
            s3_key = s3_service.upload_resume(
                file_bytes=resume_bytes,
                filename=resume.filename or "resume",
                user_id=user_id,
                content_type=resume.content_type or "application/octet-stream",
            )
            _log.info("Resume stored at s3_key=%s user_id=%s", s3_key, user_id)
        except Exception as exc:
            _log.warning("Resume S3 upload skipped: %s", exc)

    result = analyze_profile(resume_bytes, github_username)
    return ProfileAnalysisResponse(**result)


@app.post("/analyze-role", response_model=AnalyzeRoleResponse)
def analyze_role_endpoint(request: AnalyzeRoleRequest) -> AnalyzeRoleResponse:
    result = analyze_role(
        user_skills=request.user_skills,
        selected_role=request.selected_role,
    )
    return AnalyzeRoleResponse(**result)


@app.post("/generate-roadmap", response_model=GenerateRoadmapResponse)
def generate_roadmap_endpoint(request: GenerateRoadmapRequest) -> GenerateRoadmapResponse:
    missing_skills_list = [
        {"skill": skill.skill, "importance": skill.importance}
        for skill in request.missing_skills
    ]
    result = generate_roadmap(missing_skills_list)
    return GenerateRoadmapResponse(**result)


@app.post("/generate-career-plan", response_model=GenerateCareerPlanResponse)
def generate_career_plan_endpoint(
    request: GenerateCareerPlanRequest,
) -> GenerateCareerPlanResponse:
    # Delegate to the orchestrator: gap_agent → roadmap_agent pipeline
    result = run_skill_gap_pipeline(
        user_skills=request.user_skills,
        selected_role=request.selected_role,
    )

    return GenerateCareerPlanResponse(
        alignment_score=result["alignment_score"],
        missing_skills=[MissingSkill(**skill) for skill in result["missing_skills"]],
        roadmap=result["roadmap"],
        capstone=result["capstone"],
        review=result["review"],
    )


@app.post("/skill-impact", response_model=SkillImpactResponse)
def skill_impact(payload: SkillImpactRequest) -> SkillImpactResponse:
    """Rank every skill gap for the target role by Skill Impact Score.

    The score combines market demand, gap severity, career relevance, and the
    user's current mastery level.  Pass ``user_id`` to have verified skills
    fetched from DynamoDB so the score reflects actual assessed competency.
    """
    # Fetch verified skills + skill_xp_map from DynamoDB if user_id provided
    verified: set[str] = set()
    skill_xp_map: dict[str, int] = {}
    if payload.user_id:
        try:
            user = user_store.get_user(payload.user_id)
            verified = set(user.get("verified_skills", []))
            skill_xp_map = user_store.get_skill_xp_map(payload.user_id)
        except Exception:
            pass  # graceful degradation — proceed without verified skills

    ranked = skill_impact_engine.compute_impact_scores(
        user_skills=payload.user_skills,
        target_role=payload.target_role,
        verified_skills=verified,
        skill_xp_map=skill_xp_map,
    )

    alignment = skill_impact_engine.compute_alignment_score(
        user_skills=payload.user_skills,
        target_role=payload.target_role,
        verified_skills=verified,
    )

    top_priority = skill_impact_engine.get_top_priority_skill(
        user_skills=payload.user_skills,
        target_role=payload.target_role,
        verified_skills=verified,
        skill_xp_map=skill_xp_map,
    )

    return SkillImpactResponse(
        target_role=payload.target_role,
        ranked_skills=[SkillImpactScoreItem(**item) for item in ranked],
        top_priority=top_priority,
        alignment_score=alignment,
    )


@app.post("/verify-skill/challenge", response_model=VerifyChallengeResponse)
def get_skill_challenge(request: VerifyChallengeRequest) -> VerifyChallengeResponse:
    """Generate a challenge question for the requested skill."""
    question = verification_agent.generate_challenge(request.skill)
    return VerifyChallengeResponse(skill=request.skill, question=question)


@app.post("/verify-skill/check", response_model=VerifyAnswerResponse)
def check_skill_answer(request: VerifyAnswerRequest) -> VerifyAnswerResponse:
    """Evaluate a user's answer and return a verification result.

    If *user_id* is provided and the answer is verified (score >= 70),
    the skill is persisted to the user's DynamoDB record.
    """
    result = verification_agent.verify_answer(
        skill=request.skill,
        question=request.question,
        answer=request.answer,
    )

    if request.user_id and result.verified:
        try:
            user_store.add_verified_skill(request.user_id, request.skill)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "Failed to persist verified skill '%s' for user '%s': %s",
                request.skill, request.user_id, exc,
            )

    return VerifyAnswerResponse(**result.to_dict())


# ── Mastery ───────────────────────────────────────────────────────────────────────

@app.get("/user/{user_id}/mastery", response_model=UserMasteryResponse)
def get_user_mastery(user_id: str) -> UserMasteryResponse:
    """Return per-skill mastery levels for a user.

    Combines self-reported skills, verified skills, accumulated skill XP, and
    GitHub mastery signals (if the user has linked a GitHub account) to produce
    a 5-level mastery assessment (0=unknown → 4=expert) for every skill.
    """
    try:
        user = user_store.get_user(user_id)
    except Exception as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"User '{user_id}' not found") from exc

    user_skills    = user.get("user_skills", []) or user.get("skills", [])
    verified_skills = set(user.get("verified_skills", []))
    skill_xp_map   = user_store.get_skill_xp_map(user_id)

    # GitHub signals if available
    github_mastery_signals: dict[str, float] = {}
    github_username = user.get("github_username")
    if github_username:
        try:
            from app.services.github_service import analyze_github_deep
            gh = analyze_github_deep(github_username)
            github_mastery_signals = gh.get("mastery_signals", {})
        except Exception:
            pass

    mastery_data = mastery_tracker.compute_mastery_for_all_skills(
        user_skills=user_skills,
        verified_skills=verified_skills,
        skill_xp_map=skill_xp_map,
        github_mastery_signals=github_mastery_signals,
    )

    items = [
        MasteryLevelItem(
            skill=skill,
            level=info["level"],
            level_name=info["level_name"],
            mastery_discount=info["mastery_discount"],
            skill_xp=skill_xp_map.get(skill, 0),
        )
        for skill, info in mastery_data.items()
    ]
    # Sort by level descending, then by skill_xp descending
    items.sort(key=lambda x: (x.level, x.skill_xp), reverse=True)

    return UserMasteryResponse(user_id=user_id, mastery_levels=items)


# ── Market Intelligence ──────────────────────────────────────────────────────

@app.post("/market/refresh", response_model=MarketRefreshResponse)
def refresh_market(write: bool = True) -> MarketRefreshResponse:
    """Fetch live job listings and update market_skills.json.

    Pulls from RemoteOK (always) and Adzuna (when ``ADZUNA_APP_ID``/
    ``ADZUNA_APP_KEY`` env vars are set).  Merges 80 live / 20 static.

    Args:
        write: persist updates to market_skills.json in /tmp + S3 (default True).
    """
    result = market_service.refresh_market_data(write=write)

    if write and result.get("roles_updated", 0) > 0:
        # Reload in-process caches so the current Lambda process uses fresh data
        import app.services.role_engine as _re
        import app.services.skill_impact_engine as _sie
        _re.MARKET_DATA = market_service.get_market_data()
        _sie._market_data = None  # force lazy-reload on next call

    return MarketRefreshResponse(**result)


# ── Agentic Intelligence Loop ─────────────────────────────────────────────────

@app.post("/agent/run/{user_id}")
def run_agent(user_id: str):
    """Run the full Agentic Intelligence Loop for a user.

    This is the core of the agentic AI system. It autonomously:
      1. OBSERVE  — gather all available signals about the user's state
      2. REASON   — LLM analyzes the state and decides the highest-impact action
      3. PLAN     — build a structured sequence of tool calls
      4. ACT      — execute each planned tool autonomously
      5. REFLECT  — store results, update user state, return insights

    Unlike every other endpoint (which are reactive — triggered by user clicks),
    this endpoint runs the agent proactively. The frontend polls it regularly
    so the agent continuously works toward the user's career goal.
    """
    from app.agents.agentic_loop import run_agent_loop
    return run_agent_loop(user_id)


# ── Agent: Daily Challenge ────────────────────────────────────────────────────

@app.get("/agent/challenge/{user_id}")
def get_daily_challenge(user_id: str):
    """Generate today's adaptive daily challenge for the user's priority skill.

    Challenge type and difficulty are automatically calibrated to the user's
    current mastery level (challenge_agent).
    """
    from app.agents import challenge_agent
    from app.services import user_store

    db_user = user_store.get_user(user_id) or {}
    skill = db_user.get("next_priority_skill") or "Python"
    mastery_level = db_user.get("mastery_level") or 0
    return challenge_agent.generate(
        user_id=user_id,
        skill=skill,
        mastery_level=int(mastery_level),
    )


@app.post("/agent/challenge/{user_id}/evaluate")
def evaluate_challenge(user_id: str, payload: dict):
    """Evaluate a user's answer to their daily challenge.

    Expects JSON body: {"challenge": {...}, "answer": "..."}
    Returns pass/fail, XP earned, streak, and detailed feedback.
    """
    from app.agents import challenge_agent

    challenge = payload.get("challenge", {})
    answer = payload.get("answer", "")
    return challenge_agent.evaluate(
        user_id=user_id,
        challenge=challenge,
        answer_text=answer,
    )


# ── Agent: Project Generation ─────────────────────────────────────────────────

@app.get("/agent/project/{user_id}")
def get_personalized_project(user_id: str):
    """Generate a unique personalised hands-on project for the user.

    Projects are seeded by user_id + skill so each user gets a different
    project and repeated requests return stable results (idempotent seed).
    Includes a 3-level hint system (project_agent).
    """
    from app.agents import project_agent
    from app.services import user_store

    db_user = user_store.get_user(user_id) or {}
    skill = db_user.get("next_priority_skill") or "Python"
    target_role = db_user.get("target_role") or "Software Engineer"
    mastery_level = db_user.get("mastery_level") or 0
    completed_projects = db_user.get("completed_projects") or []
    return project_agent.run(
        user_id=user_id,
        skill=skill,
        target_role=target_role,
        mastery_level=int(mastery_level),
        completed_projects=completed_projects,
    )


@app.post("/agent/project/{user_id}/evaluate")
def evaluate_project(user_id: str, payload: dict):
    """Autonomously evaluate a GitHub repository submission.

    Expects JSON body: {"github_repo_url": "...", "project": {...}, "skill": "..."}
    Fetches the repo, analyses code quality, and returns score + mastery delta.
    """
    from app.agents import evaluation_agent

    return evaluation_agent.run(
        user_id=user_id,
        github_repo_url=payload.get("github_repo_url", ""),
        project=payload.get("project", {}),
        skill=payload.get("skill", ""),
    )


# ── Agent: Precision Resources ────────────────────────────────────────────────

@app.get("/agent/resources/{user_id}")
def get_precision_resources(user_id: str, skill: str | None = None):
    """Return precision-curated learning resources for the user's priority skill.

    Resources include exact doc section URLs, specific course modules, video
    timestamps, and targeted GitHub examples — no generic homepage links
    (resource_agent).
    """
    from app.agents import resource_agent
    from app.services import user_store

    db_user = user_store.get_user(user_id) or {}
    target_skill = skill or db_user.get("next_priority_skill") or "Python"
    target_role = db_user.get("target_role") or "Software Engineer"
    mastery_level = db_user.get("mastery_level") or 0
    return {
        "skill": target_skill,
        "resources": resource_agent.run(
            skill=target_skill,
            target_role=target_role,
            mastery_level=int(mastery_level),
            max_resources=6,
        ),
    }


# ── Agent: Market Intelligence ────────────────────────────────────────────────

@app.get("/agent/market/{user_id}")
def get_market_intelligence(user_id: str):
    """Return live market intelligence for the user's target role.

    Detects emerging skills, computes demand weights, and reports market
    saturation relative to the user's current skill set (market_agent).
    """
    from app.agents import market_agent
    from app.services import user_store

    db_user = user_store.get_user(user_id) or {}
    target_role = db_user.get("target_role") or "Software Engineer"
    learned_skills = db_user.get("learned_skills") or []
    return market_agent.run(
        user_skills=learned_skills,
        target_role=target_role,
        force_refresh=False,
    )


# ── Agent: Progress / Feedback ─────────────────────────────────────────────────

@app.get("/agent/progress/{user_id}")
def get_progress_summary(user_id: str):
    """Return a unified learning progress snapshot (feedback_agent).

    Includes XP, level, streak, consistency score, skill mastery,
    completed task count, and XP to next level.
    """
    from app.agents import feedback_agent

    return feedback_agent.get_progress_summary(user_id)


# ── Learning Resources ────────────────────────────────────────────────────────

@app.post("/get-resources", response_model=GetResourcesResponse)
def get_learning_resources(payload: GetResourcesRequest) -> GetResourcesResponse:
    """Return curated learning resources for a specific roadmap day topic.

    Uses Bedrock Nova Pro to generate a mix of YouTube search links, official
    docs, free platform links, and practice sites — all targeted to the
    exact topic/skill so they're genuinely useful rather than generic.
    """
    items = resources_engine.get_resources(
        topic=payload.topic,
        skill=payload.skill,
        role=payload.role or "",
    )
    return GetResourcesResponse(
        topic=payload.topic,
        resources=[LearningResource(**r) for r in items["resources"]],
        repos=[GitHubRepo(**r) for r in items["repos"]],
    )
