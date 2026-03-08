# CareerCoach agent layer — 9 specialized autonomous agents
#
# Pipeline order:
#   skill_agent → market_agent → gap_agent → roadmap_agent
#       → project_agent → evaluation_agent / challenge_agent
#       → resource_agent → feedback_agent
#
# Orchestrated by: agentic_loop.py (OBSERVE → REASON → PLAN → ACT → REFLECT)
#
# Import agents directly from their modules, e.g.:
#   from app.agents import skill_agent
#   from app.agents.skill_agent import run
