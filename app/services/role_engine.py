"""
Role analysis engine using market skill data.

Loads skill frequencies via market_service.get_market_data() which resolves
/tmp (hot), S3 (persisted refresh), then the bundled static file.
"""

from app.services.skill_curation import get_skill_curation
from app.services import market_service


def _load_market_data() -> dict:
    try:
        return market_service.get_market_data()
    except Exception:
        return {}


MARKET_DATA = _load_market_data()


def analyze_role(user_skills: list[str], selected_role: str) -> dict:
    if selected_role not in MARKET_DATA:
        return {
            "alignment_score": 0.0,
            "missing_skills": [],
        }

    role_skills = MARKET_DATA[selected_role]
    user_skills_normalized = [s.lower().strip() for s in user_skills]

    total_weight = 0
    earned_weight = 0
    missing_skills = []

    for skill, frequency in role_skills.items():
        importance_weight = round(frequency * 10)
        total_weight += importance_weight

        if skill.lower() in user_skills_normalized:
            earned_weight += importance_weight
        else:
            percentage = round(frequency * 100, 2)
            why_this_skill_matters = (
                f"{skill} appears in {percentage}% of {selected_role} job postings "
                f"and is critical for {selected_role}-level responsibilities."
            )
            market_signal = (
                f"Mentioned in {percentage}% of {selected_role} postings."
            )
            curation = get_skill_curation(skill.lower().strip())
            missing_skills.append(
                {
                    "skill": skill,
                    "importance": importance_weight,
                    "why_this_skill_matters": why_this_skill_matters,
                    "market_signal": market_signal,
                    "learning_resources": curation.get("learning_resources", []),
                    "recommended_project": curation.get("recommended_project", {}),
                    "checkpoints": curation.get("checkpoints", []),
                }
            )

    alignment_score = (
        round((earned_weight / total_weight) * 100, 2)
        if total_weight > 0
        else 0.0
    )

    missing_skills.sort(key=lambda x: x["importance"], reverse=True)

    return {
        "alignment_score": alignment_score,
        "missing_skills": missing_skills,
    }
