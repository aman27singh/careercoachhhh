"""
Agentic Intelligence Loop
=========================
This is what makes CareerCoach truly *agentic AI* — not just AI-powered features.

The difference:
  - AI-powered (what we had): User clicks → API call → predefined function → response
  - Agentic AI (what this is): Agent wakes up → observes full user state →
    LLM reasons about what to do → agent plans and acts → reflects and stores outcomes

The Loop:
  1. OBSERVE  — gather all available signals about the user's state
  2. REASON   — LLM analyzes the signals and identifies the highest-impact next action
  3. PLAN     — build a structured, prioritized action plan with tool calls
  4. ACT      — execute each planned action using available tools
  5. REFLECT  — store results, update user state, generate agent insights

Available Tools the agent can invoke:
  - analyze_skill_gaps(user_skills, target_role) → gap ranking
  - compute_skill_impact(user_skills, target_role) → impact scores
  - generate_quest(skill, level) → daily quest
  - update_mastery(user_id) → mastery recompute
  - refresh_market_data() → live job market signals
  - generate_roadmap(gaps, role) → updated career roadmap

Triggered:
  - POST /agent/run/{user_id}       (on-demand)
  - After task submission           (reactive trigger)
  - EventBridge schedule            (autonomous background run)
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from app.services.llm_service import ask_llm
from app.services.role_engine import analyze_role
from app.services import skill_impact_engine, mastery_tracker, market_service, user_store
from app.agents import (
    gap_agent,
    roadmap_agent,
    skill_agent,
    market_agent,
    project_agent,
    challenge_agent,
    resource_agent,
    feedback_agent,
)

logger = logging.getLogger(__name__)


# ── Tool definitions the agent can call ───────────────────────────────────────

AGENT_TOOLS = {
    # ── Core pipeline ────────────────────────────────────────────────────────
    "analyze_skill_gaps":    "Analyze the user's skill gaps for their target role using live market data.",
    "compute_skill_impact":  "Score each missing skill by impact: market demand × gap severity × career relevance.",
    "update_mastery":        "Recompute mastery levels across all user skills based on XP, verifications, and GitHub signals.",
    "set_priority_skill":    "Update the user's next recommended skill based on the latest re-ranking.",
    "generate_roadmap":      "Build a dynamic, prioritized learning roadmap based on current gaps and mastery.",
    # ── Market & skills ──────────────────────────────────────────────────────
    "refresh_market_data":   "Pull fresh job listing data to update what skills are in demand right now.",
    "run_market_intelligence": "Detect emerging skills and compute demand weights for the current skill set.",
    # ── Project & challenge ──────────────────────────────────────────────────
    "generate_project":      "Create a personalised, unique hands-on project for the user's priority skill.",
    "generate_challenge":    "Generate a daily adaptive challenge calibrated to the user's mastery level.",
    # ── Resources ────────────────────────────────────────────────────────────
    "curate_resources":      "Curate precision learning resources with exact URLs, timestamps, and module links.",
}


# ── Step 1: OBSERVE ───────────────────────────────────────────────────────────

def _observe(user_id: str) -> dict:
    """Gather all available signals about the user's current state."""
    try:
        db_user = user_store.get_user(user_id) or {}
    except Exception:
        db_user = {}

    from app.services.utils import load_user_metrics
    try:
        metrics = load_user_metrics(user_id)
        metrics_dict = metrics.dict() if hasattr(metrics, "dict") else {}
    except Exception:
        metrics_dict = {}

    learned_skills = db_user.get("learned_skills") or []
    verified_skills = set(db_user.get("verified_skills") or [])
    target_role = db_user.get("target_role") or metrics_dict.get("target_role", "")
    xp = db_user.get("xp") or metrics_dict.get("xp", 0)
    level = db_user.get("level") or metrics_dict.get("level", 1)
    last_agent_run = db_user.get("last_agent_run")
    last_priority_skill = db_user.get("next_priority_skill")
    skill_xp_map = db_user.get("skill_xp_map") or {}
    quest_history = db_user.get("quest_history") or []

    # Compute mastery signals
    mastery_data = {}
    if learned_skills:
        try:
            mastery_data = mastery_tracker.compute_mastery_for_all_skills(
                user_skills=learned_skills,
                verified_skills=verified_skills,
                skill_xp_map=skill_xp_map,
            )
        except Exception:
            pass

    return {
        "user_id": user_id,
        "target_role": target_role,
        "learned_skills": learned_skills,
        "verified_skills": list(verified_skills),
        "xp": xp,
        "level": level,
        "skill_xp_map": skill_xp_map,
        "mastery_data": mastery_data,
        "last_agent_run": last_agent_run,
        "last_priority_skill": last_priority_skill,
        "quest_history": quest_history[-5:],  # last 5 quests context
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Step 2: REASON ────────────────────────────────────────────────────────────

def _reason(observation: dict) -> dict:
    """Use the LLM to reason about the user's state and decide what to do next."""

    mastery_summary = []
    for skill, info in (observation.get("mastery_data") or {}).items():
        mastery_summary.append(f"{skill}: {info.get('level_name', 'unknown')}")

    prompt = f"""You are an autonomous career coaching AI agent. Your goal is to help the user become job-ready for their target role as fast as possible.

USER STATE:
- Target Role: {observation['target_role'] or 'not set'}
- Current Skills: {', '.join(observation['learned_skills']) or 'none'}
- Verified Skills: {', '.join(observation['verified_skills']) or 'none'}
- XP: {observation['xp']} | Level: {observation['level']}
- Last Priority Skill Recommended: {observation['last_priority_skill'] or 'none'}
- Mastery Levels: {'; '.join(mastery_summary[:10]) or 'not computed'}
- Recent Quest History: {', '.join(observation['quest_history']) or 'none'}

AVAILABLE TOOLS:
{json.dumps(AGENT_TOOLS, indent=2)}

INSTRUCTIONS:
Based on the user's current state, reason about:
1. What is their biggest gap right now?
2. Are they making progress or stalling?
3. What is the single most impactful action the agent should take?

Then produce a JSON action plan:
{{
  "reasoning": "<2-3 sentence analysis of the user's current situation>",
  "identified_gaps": ["<skill_1>", "<skill_2>"],
  "priority_action": "<tool_name>",
  "additional_actions": ["<tool_name>", "<tool_name>"],
  "agent_message": "<1-sentence motivational insight for the user>",
  "urgency": "high|medium|low"
}}

Respond ONLY with valid JSON."""

    try:
        raw = ask_llm(prompt)
        # Strip markdown code fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception as exc:
        logger.warning("REASON step LLM failed, using fallback: %s", exc)
        return {
            "reasoning": "Agent operating in fallback mode — LLM unavailable.",
            "identified_gaps": [],
            "priority_action": "analyze_skill_gaps",
            "additional_actions": ["compute_skill_impact", "set_priority_skill"],
            "agent_message": "Your agent is analyzing your profile. Stay focused.",
            "urgency": "medium",
        }


# ── Step 3: PLAN ──────────────────────────────────────────────────────────────

def _plan(reasoning: dict, observation: dict) -> list[dict]:
    """Build an ordered list of tool calls to execute."""
    actions = []
    seen = set()

    def add(tool: str, params: dict | None = None):
        if tool not in seen:
            seen.add(tool)
            actions.append({"tool": tool, "params": params or {}})

    # ── Fixed pipeline order (runs every loop) ───────────────────────────────
    if observation.get("target_role"):
        add("analyze_skill_gaps", {
            "user_skills": observation["learned_skills"],
            "target_role": observation["target_role"],
        })
        add("compute_skill_impact", {
            "user_skills": observation["learned_skills"],
            "target_role": observation["target_role"],
        })
        add("run_market_intelligence")  # Detect emerging skills
        add("update_mastery")           # Must run before roadmap (needs mastery state)
        add("generate_roadmap")         # Dynamic: only regens if gaps/mastery changed

    # ── LLM-decided priority action ─────────────────────────────────────────
    add(reasoning.get("priority_action", "set_priority_skill"))

    # ── Optional enrichment actions (LLM-chosen) ────────────────────────────
    for tool in reasoning.get("additional_actions", []):
        add(tool)

    # ── Always generate today's challenge and curate resources ───────────────
    add("generate_challenge")
    add("curate_resources")

    # ── Always end with priority skill update ────────────────────────────────
    add("set_priority_skill")

    return actions


# ── Step 4: ACT ───────────────────────────────────────────────────────────────

def _act(plan: list[dict], observation: dict, reasoning: dict) -> dict:
    """Execute each planned tool call and collect results."""
    results = {}
    user_id = observation["user_id"]
    user_skills = observation["learned_skills"]
    target_role = observation.get("target_role", "")

    for step in plan:
        tool = step["tool"]
        try:
            # ── Core Gap Analysis ─────────────────────────────────────────────
            if tool == "analyze_skill_gaps":
                if target_role:
                    role_analysis = analyze_role(user_skills, target_role)
                    raw_gaps = role_analysis.get("missing_skills", [])
                    gaps_dicts = [g if isinstance(g, dict) else g.dict() for g in raw_gaps]
                    enriched = gap_agent.run(user_skills, target_role, gaps_dicts)
                    results["gaps"] = enriched
                    results["alignment_score"] = role_analysis.get("alignment_score", 0)

            elif tool == "compute_skill_impact":
                if target_role:
                    impact = skill_impact_engine.compute_impact_scores(
                        user_skills=user_skills,
                        target_role=target_role,
                    )
                    results["impact_scores"] = impact[:5]

            # ── Market Intelligence Agent ─────────────────────────────────────
            elif tool == "run_market_intelligence":
                if target_role:
                    market_intel = market_agent.run(
                        user_skills=user_skills,
                        target_role=target_role,
                        force_refresh=False,
                    )
                    results["market_intelligence"] = market_intel
                    results["emerging_skills"] = market_intel.get("emerging_skills", [])[:3]
                    results["market_saturation"] = market_intel.get("market_saturation", 0)

            # ── Update Mastery ────────────────────────────────────────────────
            elif tool == "update_mastery":
                db_user = user_store.get_user(user_id) or {}
                mastery = mastery_tracker.compute_mastery_for_all_skills(
                    user_skills=user_skills,
                    verified_skills=set(db_user.get("verified_skills") or []),
                    skill_xp_map=db_user.get("skill_xp_map") or {},
                )
                results["updated_mastery"] = {
                    k: v["level_name"] for k, v in mastery.items()
                }

            # ── Refresh Market Data ───────────────────────────────────────────
            elif tool == "refresh_market_data":
                market_result = market_service.refresh_market_data(write=True)
                results["market_refresh"] = {
                    "roles_updated": market_result.get("roles_updated", 0),
                    "jobs_processed": market_result.get("total_jobs_processed", 0),
                }

            # ── Dynamic Roadmap Generation ────────────────────────────────────
            elif tool == "generate_roadmap":
                gaps = results.get("gaps") or []
                if gaps and target_role:
                    db_user = user_store.get_user(user_id) or {}
                    # Check if roadmap is stale (mastery changed or gaps changed)
                    stored_roadmap = db_user.get("roadmap")
                    stored_gap_sig = db_user.get("roadmap_gap_signature", "")
                    current_gap_sig = "|".join(sorted(g.get("skill", "") for g in gaps[:5]))
                    needs_regen = (
                        not stored_roadmap
                        or stored_gap_sig != current_gap_sig
                        or results.get("updated_mastery")  # mastery changed this loop
                    )
                    if needs_regen:
                        roadmap_result = roadmap_agent.run(gaps, target_role)
                        results["roadmap"] = roadmap_result
                        results["roadmap_regenerated"] = True
                        # Persist roadmap + gap signature so we detect staleness next run
                        try:
                            user_store.update_user(user_id, {
                                "roadmap": roadmap_result,
                                "roadmap_gap_signature": current_gap_sig,
                            })
                        except Exception:
                            pass
                    else:
                        results["roadmap"] = stored_roadmap
                        results["roadmap_regenerated"] = False

            # ── Project Generation Agent ──────────────────────────────────────
            elif tool == "generate_project":
                gaps = results.get("gaps") or []
                top_skill = (
                    results.get("impact_scores", [{}])[0].get("skill")
                    or (gaps[0].get("skill") if gaps else None)
                )
                if top_skill and target_role:
                    db_user = user_store.get_user(user_id) or {}
                    mastery_data = observation.get("mastery_data", {})
                    mastery_lvl = 0
                    if top_skill in mastery_data:
                        mastery_lvl = mastery_data[top_skill].get("level", 0)
                    completed_projects = db_user.get("completed_projects", [])
                    project = project_agent.run(
                        user_id=user_id,
                        skill=top_skill,
                        target_role=target_role,
                        mastery_level=mastery_lvl,
                        completed_projects=completed_projects,
                    )
                    results["generated_project"] = project

            # ── Daily Challenge Agent ─────────────────────────────────────────
            elif tool == "generate_challenge":
                gaps = results.get("gaps") or []
                top_skill = (
                    results.get("impact_scores", [{}])[0].get("skill")
                    or (gaps[0].get("skill") if gaps else None)
                )
                if top_skill:
                    mastery_data = observation.get("mastery_data", {})
                    mastery_lvl = 0
                    if top_skill in mastery_data:
                        mastery_lvl = mastery_data[top_skill].get("level", 0)
                    daily_challenge = challenge_agent.generate(
                        user_id=user_id,
                        skill=top_skill,
                        mastery_level=mastery_lvl,
                    )
                    results["daily_challenge"] = daily_challenge

            # ── Resource Curation Agent ───────────────────────────────────────
            elif tool == "curate_resources":
                gaps = results.get("gaps") or []
                top_skills_to_resource = [
                    g.get("skill") for g in gaps[:3] if g.get("skill")
                ]
                if top_skills_to_resource and target_role:
                    mastery_data = observation.get("mastery_data", {})
                    mastery_map = {
                        s: mastery_data.get(s, {}).get("level", 0)
                        for s in top_skills_to_resource
                    }
                    resources = resource_agent.batch_run(
                        skills=top_skills_to_resource,
                        target_role=target_role,
                        mastery_map=mastery_map,
                        resources_per_skill=3,
                    )
                    results["curated_resources"] = resources

            # ── Set Priority Skill ────────────────────────────────────────────
            elif tool == "set_priority_skill":
                top_skill = None
                if results.get("impact_scores"):
                    top_skill = results["impact_scores"][0].get("skill")
                elif results.get("gaps"):
                    top_skill = results["gaps"][0].get("skill")
                elif reasoning.get("identified_gaps"):
                    top_skill = reasoning["identified_gaps"][0]

                if top_skill:
                    user_store.set_next_priority_skill(user_id, top_skill)
                    results["priority_skill_set"] = top_skill

        except Exception as exc:
            logger.warning("ACT step '%s' failed: %s", tool, exc)
            results[f"{tool}_error"] = str(exc)

    return results


# ── Step 5: REFLECT ────────────────────────────────────────────────────────────

def _reflect(observation: dict, reasoning: dict, actions_taken: list[dict], results: dict) -> dict:
    """Summarize what was done, update user state, and generate insights."""
    user_id = observation["user_id"]
    now = datetime.now(timezone.utc).isoformat()

    # Build a human-readable action log
    action_log = []
    for step in actions_taken:
        tool = step["tool"]
        if f"{tool}_error" in results:
            action_log.append(f"⚠ {tool}: failed")
        else:
            action_log.append(f"✓ {tool}: completed")

    # Key outcomes
    outcomes = {}
    if "priority_skill_set" in results:
        outcomes["next_priority_skill"] = results["priority_skill_set"]
    if "alignment_score" in results:
        outcomes["alignment_score"] = results["alignment_score"]
    if "gaps" in results:
        outcomes["top_gaps"] = [g.get("skill") for g in results["gaps"][:3]]
    if "updated_mastery" in results:
        outcomes["mastery_updated"] = True
    if "generated_project" in results:
        outcomes["project"] = results["generated_project"].get("title", "")[:80]
    if "daily_challenge" in results:
        outcomes["challenge"] = results["daily_challenge"].get("question", "")[:80]
    if "curated_resources" in results:
        outcomes["resources_curated"] = list(results["curated_resources"].keys())
    if "emerging_skills" in results:
        outcomes["emerging_skills"] = [s.get("skill") for s in results["emerging_skills"]]
    if results.get("roadmap_regenerated"):
        outcomes["roadmap_updated"] = True

    # ── Use feedback_agent for unified XP / insight ───────────────────────────
    try:
        xp_delta = 0  # Loop itself doesn't award XP; activities do
        priority_skill = results.get("priority_skill_set")
        feedback_result = feedback_agent.record_activity(
            user_id=user_id,
            activity_type="agent_loop_completed",
            skill=priority_skill,
            xp_delta=xp_delta,
            mastery_delta=0.0,
            metadata={"outcomes": outcomes},
        )
        outcomes["insight"] = feedback_result.get("insight", "")
        outcomes["streak"] = feedback_result.get("streak", 0)
        outcomes["consistency"] = feedback_result.get("consistency_score", 0)
    except Exception as exc:
        logger.debug("_reflect: feedback_agent call failed: %s", exc)

    # Persist last_agent_run timestamp to DynamoDB
    try:
        from boto3 import resource
        import os
        table_name = os.getenv("CAREEROS_USERS_TABLE", "careeros-users")
        region = os.getenv("AWS_REGION", "us-east-1")
        table = resource("dynamodb", region_name=region).Table(table_name)
        table.update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET last_agent_run = :t",
            ExpressionAttributeValues={":t": now},
        )
    except Exception:
        pass  # non-fatal

    return {
        "agent_run_at": now,
        "loop_steps": ["OBSERVE", "REASON", "PLAN", "ACT", "REFLECT"],
        "actions_taken": action_log,
        "reasoning": reasoning.get("reasoning", ""),
        "agent_message": reasoning.get("agent_message", ""),
        "urgency": reasoning.get("urgency", "medium"),
        "outcomes": outcomes,
        "user_id": user_id,
    }


# ── Public entry point ─────────────────────────────────────────────────────────

def run_agent_loop(user_id: str) -> dict:
    """
    Run the full Agentic Intelligence Loop for a user.

    This is the core of the agentic AI system. It autonomously:
      1. Observes the user's complete state
      2. Uses the LLM to reason about what to do next
      3. Plans a sequence of tool calls
      4. Acts by executing each tool
      5. Reflects and stores the outcomes

    Returns a structured report of everything the agent did and decided.
    """
    t0 = time.time()
    logger.info("AGENTIC LOOP START — user=%s", user_id)

    # 1. OBSERVE
    observation = _observe(user_id)
    logger.info("OBSERVE — skills=%d target_role=%s xp=%d",
                len(observation["learned_skills"]),
                observation["target_role"],
                observation["xp"])

    # 2. REASON
    reasoning = _reason(observation)
    logger.info("REASON — priority_action=%s urgency=%s",
                reasoning.get("priority_action"), reasoning.get("urgency"))

    # 3. PLAN
    plan = _plan(reasoning, observation)
    logger.info("PLAN — %d actions: %s", len(plan), [s["tool"] for s in plan])

    # 4. ACT
    results = _act(plan, observation, reasoning)
    logger.info("ACT — results keys: %s", list(results.keys()))

    # 5. REFLECT
    reflection = _reflect(observation, reasoning, plan, results)
    elapsed = round(time.time() - t0, 2)

    logger.info("AGENTIC LOOP COMPLETE — user=%s elapsed=%.2fs", user_id, elapsed)

    return {
        **reflection,
        "elapsed_s": elapsed,
        "observation_snapshot": {
            "target_role": observation["target_role"],
            "skill_count": len(observation["learned_skills"]),
            "xp": observation["xp"],
            "level": observation["level"],
        },
    }
