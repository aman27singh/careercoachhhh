/**
 * CareerCoach API Client
 * ======================
 * Centralised fetch wrapper for all FastAPI backend calls.
 *
 * Configuration
 * -------------
 * Set VITE_API_URL in a .env file to override the default base URL:
 *   VITE_API_URL=http://my-server:8000
 *
 * Functions
 * ---------
 *   analyzeProfile(formData)          POST /analyze-profile   (multipart)
 *   generateCareerPlan(data)          POST /generate-career-plan
 *   evaluateTask(data)                POST /submit-task
 */

const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000'

/**
 * Shared response handler — throws a descriptive Error on non-2xx status.
 * @param {Response} res
 * @returns {Promise<any>}
 */
async function _handleResponse(res) {
  if (!res.ok) {
    let message = `Server error (HTTP ${res.status})`
    try {
      const body = await res.json()
      message = body.detail ?? JSON.stringify(body)
    } catch {
      // ignore JSON parse failures — keep the generic message
    }
    throw new Error(message)
  }
  return res.json()
}

/**
 * Analyze a user's resume / GitHub profile and extract skills.
 *
 * @param {FormData} formData  Fields: `resume` (File, optional),
 *                             `github_username` (string, optional)
 * @returns {Promise<ProfileAnalysisResponse>}
 */
export async function analyzeProfile(formData) {
  const res = await fetch(`${BASE_URL}/analyze-profile`, {
    method: 'POST',
    body: formData,   // let the browser set Content-Type (multipart boundary)
  })
  return _handleResponse(res)
}

/**
 * Run the full career-plan pipeline: gap analysis + 30-day roadmap.
 *
 * @param {{ user_skills: string[], selected_role: string }} data
 * @returns {Promise<GenerateCareerPlanResponse>}
 *   { alignment_score, missing_skills, roadmap, capstone, review }
 */
export async function generateCareerPlan(data) {
  const res = await fetch(`${BASE_URL}/generate-career-plan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  return _handleResponse(res)
}

/**
 * Submit a task answer for AI evaluation and XP reward.
 *
 * @param {{ user_id: string, submission_text: string }} data
 * @returns {Promise<SubmitTaskResponse>}
 *   { xp, level, rank, streak, execution_score, feedback }
 */
export async function evaluateTask(data) {
  const res = await fetch(`${BASE_URL}/submit-task`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  return _handleResponse(res)
}

/**
 * Generate an AI challenge question for a given skill.
 *
 * @param {string} skill  The skill to generate a challenge for.
 * @returns {Promise<{skill: string, question: string}>}
 */
export async function generateChallenge(skill) {
  const res = await fetch(`${BASE_URL}/verify-skill/challenge`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ skill }),
  })
  return _handleResponse(res)
}

/**
 * Compute skill impact scores for a target role.
 *
 * @param {{ user_skills: string[], target_role: string, user_id?: string }} data
 * @returns {Promise<SkillImpactResponse>}
 */
export async function getSkillImpact(data) {
  const res = await fetch(`${BASE_URL}/skill-impact`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  return _handleResponse(res)
}

/**
 * Refresh live market data from RemoteOK, JSearch (Indeed/LinkedIn/Glassdoor), and Adzuna.
 *
 * @returns {Promise<{ roles_updated, total_jobs_processed, sources, elapsed_s, written }>}
 */
export async function refreshMarketData() {
  const res = await fetch(`${BASE_URL}/market/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  })
  return _handleResponse(res)
}

export async function getLearningResources(topic, skill, role) {
  const res = await fetch(`${BASE_URL}/get-resources`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ topic, skill, role: role || '' }),
  })
  return _handleResponse(res)
}

/**
 * Fetch per-skill mastery levels for a user from the Mastery Tracker.
 *
 * @param {string} userId
 * @returns {Promise<{ user_id: string, mastery_levels: Array<{skill,level,level_name,mastery_discount,skill_xp}> }>}
 */
export async function getUserMastery(userId) {
  const res = await fetch(`${BASE_URL}/user/${userId}/mastery`)
  return _handleResponse(res)
}

/**
 * Run the full Agentic Intelligence Loop for a user.
 *
 * This is the core of the agentic AI system — it does:
 *   OBSERVE → REASON → PLAN → ACT → REFLECT
 *
 * Unlike all other API calls (which are reactive — called by user clicks),
 * this is called proactively on a timer so the agent continuously works
 * toward the user's career goal without waiting for interaction.
 *
 * @param {string} userId
 * @returns {Promise<AgentLoopReport>}
 */
export async function runAgentLoop(userId) {
  const res = await fetch(`${BASE_URL}/agent/run/${userId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  })
  return _handleResponse(res)
}
