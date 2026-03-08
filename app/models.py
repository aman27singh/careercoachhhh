from pydantic import BaseModel


class UserMetrics(BaseModel):
    user_id: str
    xp: int
    level: int
    rank: str
    streak: int
    total_completed_tasks: int
    total_assigned_tasks: int
    execution_score: float
    last_submission_date: str | None = None
    learned_skills: list[str] = []  # skills practised via Daily Quest (persisted in DynamoDB)
    skill_distribution: dict[str, int] = {
        "Technical": 65,
        "System Design": 40,
        "Execution": 78,
        "Soft Skills": 50,
        "Strategic": 30
    }
    activity_log: list[dict[str, int | str]] = [
        {"day": "Mon", "xp": 45},
        {"day": "Tue", "xp": 52},
        {"day": "Wed", "xp": 38},
        {"day": "Thu", "xp": 65},
        {"day": "Fri", "xp": 48}
    ]
    knowledge_map: list[dict[str, int | str]] = [
        {"name": "Backend", "value": 40, "color": "var(--accent-primary)"},
        {"name": "Frontend", "value": 25, "color": "var(--accent-secondary)"},
        {"name": "DevOps", "value": 20, "color": "#8B5CF6"},
        {"name": "AI/ML", "value": 15, "color": "#F59E0B"}
    ]


class RoleGap(BaseModel):
    selected_role: str
    alignment_score: float
    skills: list[str]


class QuestTask(BaseModel):
    task_id: str
    skill: str
    task_type: str
    xp_reward: int
    completed: bool


class TaskFeedback(BaseModel):
    rating: int
    mistakes: list[str]
    correct_approach: str
    improvements: list[str]


class SubmitTaskRequest(BaseModel):
    user_id: str
    submission_text: str
    quality_score: int | None = None
    skill: str | None = None          # skill being demonstrated for verification
    target_role: str | None = None    # used for post-eval re-ranking
    user_skills: list[str] | None = None  # current user skill list for re-ranking


class VerifyChallengeRequest(BaseModel):
    skill: str


class VerifyChallengeResponse(BaseModel):
    skill: str
    question: str


class VerifyAnswerRequest(BaseModel):
    skill: str
    question: str
    answer: str
    user_id: str | None = None  # when provided, verified skills are persisted


class VerifyAnswerResponse(BaseModel):
    skill: str
    question: str
    score: int
    feedback: str
    verified: bool
    strengths: list[str]
    gaps: list[str]


class SubmitTaskResponse(BaseModel):
    xp: int
    level: int
    rank: str
    streak: int
    execution_score: float
    feedback: TaskFeedback | None = None
    next_priority_skill: str | None = None  # top re-ranked gap skill after task eval


class GithubAnalysis(BaseModel):
    repo_count: int
    primary_languages: list[str]
    language_breakdown: dict[str, int]
    frameworks_detected: list[str] = []
    activity: dict = {}


class SkillRating(BaseModel):
    skill: str
    score: int           # 0-100
    level: str           # Beginner / Intermediate / Advanced / Expert
    evidence: str | None = None   # why this rating was given


class ProjectItem(BaseModel):
    name: str
    description: str
    technologies: list[str] = []
    complexity: str | None = None   # Simple / Medium / Complex
    highlights: list[str] = []


class ProfileAnalysisResponse(BaseModel):
    # core fields (backward compatible)
    technical_skills: list[str]
    soft_skills: list[str]
    experience_level: str
    github_analysis: GithubAnalysis
    # enriched fields
    summary: str | None = None
    years_of_experience: int | None = None
    skill_ratings: list[SkillRating] = []
    projects: list[ProjectItem] = []
    education: list[str] = []
    certifications: list[str] = []
    strengths: list[str] = []
    improvement_areas: list[str] = []


class MissingSkill(BaseModel):
    skill: str
    importance: int
    why_this_skill_matters: str | None = None
    market_signal: str | None = None
    learning_resources: list[str] | None = None
    recommended_project: dict | None = None
    checkpoints: list[str] | None = None


class AnalyzeRoleRequest(BaseModel):
    user_skills: list[str]
    selected_role: str


class AnalyzeRoleResponse(BaseModel):
    alignment_score: float
    missing_skills: list[MissingSkill]


class DailyTask(BaseModel):
    day: int
    task: str
    description: str


class WeekPlan(BaseModel):
    week: int
    focus_skill: str
    importance: int
    days: list[DailyTask]


class CapstoneDay(BaseModel):
    day: int
    task: str
    description: str


class GenerateRoadmapRequest(BaseModel):
    missing_skills: list[MissingSkill]


class GenerateRoadmapResponse(BaseModel):
    roadmap: list[WeekPlan]
    capstone: CapstoneDay
    review: CapstoneDay
    total_days: int
    total_skills: int


class GenerateCareerPlanRequest(BaseModel):
    user_skills: list[str]
    selected_role: str


class GenerateCareerPlanResponse(BaseModel):
    alignment_score: float
    missing_skills: list[MissingSkill]
    roadmap: list[WeekPlan]
    capstone: CapstoneDay
    review: CapstoneDay


# ── Skill Impact Scoring Engine ───────────────────────────────────────────────

class SkillImpactScoreItem(BaseModel):
    skill: str
    impact_score: float           # 0–100 composite score
    market_demand: float          # 0–1 from job listing frequency
    gap_severity: float           # 0–1 (absent=1.0, self-reported=0.4, verified=0.0)
    career_relevance: float       # 0–1 rank-normalised position in role
    mastery_discount: float       # 0–1 reduction applied for known skills
    mastery_level: int | str      # int 0-4 from mastery_tracker, or legacy str
    mastery_level_name: str = ""  # human-readable name
    priority_rank: int            # 1-indexed rank (1 = highest impact)


# ── Mastery Tracking ──────────────────────────────────────────────────────────

class MasteryLevelItem(BaseModel):
    skill: str
    level: int              # 0 (unknown) → 4 (expert)
    level_name: str         # "unknown"|"learning"|"practicing"|"proficient"|"expert"
    mastery_discount: float # 0.00 → 0.80
    skill_xp: int           # accumulated XP for this skill


class UserMasteryResponse(BaseModel):
    user_id: str
    mastery_levels: list[MasteryLevelItem]


# ── Market ────────────────────────────────────────────────────────────────────

class MarketRefreshResponse(BaseModel):
    roles_updated: int
    total_jobs_processed: int
    sources: dict
    elapsed_s: float
    written: bool


class GetResourcesRequest(BaseModel):
    topic: str          # specific day task description
    skill: str          # broad skill (e.g. "Vue Router")
    role: str | None = None  # target role for context


class LearningResource(BaseModel):
    type: str           # youtube | docs | article | practice | course
    title: str
    url: str
    description: str


class GitHubRepo(BaseModel):
    name: str           # owner/repo  e.g. "vuejs/vue"
    url: str            # https://github.com/owner/repo
    description: str    # what the repo does
    stars: str          # approximate star count string e.g. "~207k"
    why: str            # why this repo is useful for this topic


class GetResourcesResponse(BaseModel):
    topic: str
    resources: list[LearningResource]
    repos: list[GitHubRepo] = []


class SkillImpactRequest(BaseModel):
    user_skills: list[str]
    target_role: str
    user_id: str | None = None    # if provided, verified skills fetched from DynamoDB


class SkillImpactResponse(BaseModel):
    target_role: str
    ranked_skills: list[SkillImpactScoreItem]
    top_priority: str | None      # single highest-impact skill to learn next
    alignment_score: float        # % of top-10 role skills already covered
