import { useState, useRef, useEffect } from 'react'
import './App.css'
import { analyzeProfile, generateCareerPlan, evaluateTask, generateChallenge, getSkillImpact, refreshMarketData, getLearningResources, getUserMastery } from './api/careerCoachApi'

const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000'
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  Legend,
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Radar,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  AreaChart,
  Area
} from 'recharts'
import {
  LayoutDashboard,
  ScanFace,
  Target,
  Map,
  Swords,
  BarChart2,
  Flame,
  Zap,
  Trophy,
  ChevronRight,
  TrendingUp,
  Award,
  Lock,
  Menu,
  Upload,
  Github,
  Sparkles,
  FileText,
  Users,
  ExternalLink,
  BookOpen,
  Cpu
} from 'lucide-react'

const _getOb = () => { try { return JSON.parse(localStorage.getItem('careeros_onboarding')) } catch { return null } }

function App() {
  const [activeTab, setActiveTab] = useState('dashboard')
  const [scanResult, setScanResult] = useState(null)
  const [userAddedSkills, setUserAddedSkills] = useState(() => {
    try { return JSON.parse(localStorage.getItem('careeros_added_skills') || '[]') } catch { return [] }
  })
  const [gapResult, setGapResult] = useState(null)
  const [metrics, setMetrics] = useState(null)
  const [loading, setLoading] = useState(true)

  const [onboardingData, setOnboardingData] = useState(_getOb)
  const [userName, setUserName] = useState(() => _getOb()?.name || localStorage.getItem('careeros_username') || '')
  const [selectedRole, setSelectedRole] = useState(() => _getOb()?.targetRole || '')
  const [masteryData, setMasteryData] = useState(null)
  const [marketStats, setMarketStats] = useState(() => {
    try { return JSON.parse(localStorage.getItem('careeros_market_stats') || 'null') } catch { return null }
  })

  const handleOnboardingComplete = async (data) => {
    // Strip the File object before persisting (not serialisable)
    const { resumeFile, ...persistable } = data
    localStorage.setItem('careeros_onboarding', JSON.stringify(persistable))
    localStorage.setItem('careeros_username', data.name)
    setOnboardingData(persistable)
    setUserName(data.name)
    if (data.targetRole) setSelectedRole(data.targetRole)
    // Run profile scan in background if resume or github was provided
    if (resumeFile || data.githubUsername) {
      try {
        const fd = new FormData()
        if (resumeFile) fd.append('resume', resumeFile)
        if (data.githubUsername) fd.append('github_username', data.githubUsername)
        const result = await analyzeProfile(fd)
        setScanResult(result)
      } catch (e) { console.error('Onboarding scan failed', e) }
    }
  }

  const handleSetName = (name) => {
    setUserName(name)
    localStorage.setItem('careeros_username', name)
  }

  const fetchMetrics = async () => {
    try {
      const resp = await fetch(`${BASE_URL}/metrics/user_1`)
      const data = await resp.json()
      setMetrics(data)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchMetrics()
  }, [])

  // Auto-sync market data if cache is empty or older than 2 hours
  useEffect(() => {
    const TWO_HOURS = 2 * 60 * 60 * 1000
    const stale = !marketStats?.refreshed_at ||
      Date.now() - new Date(marketStats.refreshed_at).getTime() > TWO_HOURS
    if (stale) {
      refreshMarketData().then(data => {
        const stats = { ...data, refreshed_at: new Date().toISOString() }
        setMarketStats(stats)
        localStorage.setItem('careeros_market_stats', JSON.stringify(stats))
      }).catch(() => {})
    }
  }, [])

  // Fetch per-skill mastery from Mastery Tracker
  useEffect(() => {
    getUserMastery('user_1').then(setMasteryData).catch(() => {})
  }, [])

  if (loading) return <div className="loading-state"><Sparkles className="spin" /></div>

  // Single source-of-truth for "all skills this user knows"
  // Merges: profile scan results + practised skills from backend + manually entered chips
  const allKnownSkills = [...new Set([
    ...(scanResult?.technical_skills || []),
    ...(scanResult?.github_analysis?.primary_languages || []),
    ...(metrics?.learned_skills || []),
    ...userAddedSkills,
  ])]

  return (
    <div className="app-container">
      {!onboardingData && <Onboarding onComplete={handleOnboardingComplete} />}
      <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} metrics={metrics} />
      <main className="main-content">
        <DashboardHeader metrics={metrics} />

        {activeTab === 'dashboard' && <Dashboard metrics={metrics} setActiveTab={setActiveTab} userName={userName} onSetName={handleSetName} masteryData={masteryData} marketStats={marketStats} />}
        {activeTab === 'profile-scan' && (
          <ProfileScan result={scanResult} setResult={setScanResult} />
        )}
        {activeTab === 'role-gap' && (
          <RoleGap
            userSkills={allKnownSkills}
            userAddedSkills={userAddedSkills}
            onAddSkill={(s) => {
              const updated = [...new Set([...userAddedSkills, s])]
              setUserAddedSkills(updated)
              localStorage.setItem('careeros_added_skills', JSON.stringify(updated))
            }}
            onRemoveSkill={(s) => {
              const updated = userAddedSkills.filter(x => x !== s)
              setUserAddedSkills(updated)
              localStorage.setItem('careeros_added_skills', JSON.stringify(updated))
            }}
            gapResult={gapResult}
            setGapResult={setGapResult}
            selectedRole={selectedRole}
            setSelectedRole={setSelectedRole}
            marketStats={marketStats}
            setMarketStats={(stats) => {
              setMarketStats(stats)
              localStorage.setItem('careeros_market_stats', JSON.stringify(stats))
            }}
          />
        )}
        {activeTab === 'quest-map' && (
          <QuestMap
            gapResult={gapResult}
            userSkills={allKnownSkills}
            selectedRole={selectedRole}
          />
        )}
        {activeTab === 'daily-quest' && (
          <DailyQuest
            onComplete={fetchMetrics}
            selectedRole={selectedRole}
            allUserSkills={allKnownSkills}
            nextPrioritySkill={metrics?.next_priority_skill}
          />
        )}
        {activeTab === 'stats' && (
          <PlayerStats metrics={metrics} fetchMetrics={fetchMetrics} selectedRole={selectedRole} scanResult={scanResult} masteryData={masteryData} />
        )}
        {/* Placeholders for other tabs */}
        {activeTab !== 'dashboard' && activeTab !== 'profile-scan' && activeTab !== 'role-gap' && activeTab !== 'quest-map' && activeTab !== 'daily-quest' && activeTab !== 'stats' && (
          <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-muted)' }}>
            Feature coming soon...
          </div>
        )}
      </main>
    </div>
  )
}


// ─── Onboarding data ────────────────────────────────────────────────────────
const ONBOARDING_ROLES = [
  { id: 'Backend Developer',         icon: '⚙️', desc: 'APIs, databases, system design' },
  { id: 'Frontend Developer',        icon: '🎨', desc: 'UI, React, user experience' },
  { id: 'Full Stack Developer',      icon: '💻', desc: 'Frontend + Backend combined' },
  { id: 'Data Analyst',              icon: '📊', desc: 'SQL, Excel, visualization' },
  { id: 'Machine Learning Engineer', icon: '🤖', desc: 'ML, PyTorch, model deployment' },
  { id: 'DevOps Engineer',           icon: '🚀', desc: 'CI/CD, Docker, Kubernetes' },
]
const ONBOARDING_SEGMENTS = [
  { id: 'student',      label: 'University Student',   icon: '🎓', desc: 'Building skills to land my first job' },
  { id: 'self_learner', label: 'Self-Learner',         icon: '📚', desc: 'Learning on my own schedule' },
  { id: 'professional', label: 'Working Professional', icon: '💼', desc: 'Upskilling or switching roles' },
]
const ONBOARDING_HOURS = [5, 10, 20, 30]
const ONBOARDING_DURATIONS = [1, 3, 6, 12]

// ─── Onboarding wizard ──────────────────────────────────────────────────────
const Onboarding = ({ onComplete }) => {
  const [step, setStep] = useState(1)
  const TOTAL = 5
  const [form, setForm] = useState({ name: '', segment: '', targetRole: '', weeklyHours: 10, durationMonths: 3, resumeFile: null, githubUsername: '' })
  const resumeRef = useRef(null)

  const canNext = () => {
    if (step === 1) return form.name.trim().length > 0
    if (step === 2) return form.segment !== ''
    if (step === 3) return form.targetRole !== ''
    return true   // step 4 (commitment) + step 5 (resume/github) always passable
  }

  const skip = () => onComplete({ name: 'Adventurer', segment: 'self_learner', targetRole: '', weeklyHours: 10, durationMonths: 3, resumeFile: null, githubUsername: '' })

  const btnBase = {
    padding: '0.65rem 1.75rem', borderRadius: '10px', cursor: 'pointer',
    fontWeight: 700, border: 'none', fontSize: '0.9rem', transition: 'all 0.2s'
  }

  return (
    <div style={{
      position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh',
      background: 'rgba(0,0,0,0.93)', backdropFilter: 'blur(10px)',
      zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center'
    }}>
      <div style={{
        background: 'var(--bg-secondary)', border: '1px solid var(--border-color)',
        borderRadius: '20px', width: '540px', maxWidth: '94vw',
        padding: '2.5rem', boxShadow: '0 24px 80px rgba(0,0,0,0.6)'
      }}>

        {/* Progress bar */}
        <div style={{ display: 'flex', gap: '6px', marginBottom: '2rem' }}>
          {Array.from({ length: TOTAL }).map((_, i) => (
            <div key={i} style={{
              flex: 1, height: '4px', borderRadius: '2px',
              background: i < step ? 'var(--accent-primary)' : 'var(--border-color)',
              transition: 'background 0.3s'
            }} />
          ))}
        </div>

        {/* Step 1 — Name */}
        {step === 1 && (
          <div>
            <div style={{ fontSize: '2.5rem', marginBottom: '0.75rem' }}>👋</div>
            <h2 style={{ margin: '0 0 0.5rem' }}>Welcome to <span style={{ color: 'var(--accent-primary)' }}>CareerOS</span></h2>
            <p style={{ color: 'var(--text-muted)', marginBottom: '2rem', fontSize: '0.9rem', lineHeight: 1.6 }}>
              AI-powered career acceleration. Skill gaps → ranked roadmap → daily quests → verified mastery.
            </p>
            <label style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.85rem', color: 'var(--text-muted)' }}>What should we call you?</label>
            <input
              autoFocus
              className="custom-input"
              style={{ width: '100%', boxSizing: 'border-box' }}
              placeholder="Your name"
              value={form.name}
              onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
              onKeyDown={e => e.key === 'Enter' && canNext() && setStep(2)}
            />
          </div>
        )}

        {/* Step 2 — Segment */}
        {step === 2 && (
          <div>
            <h2 style={{ margin: '0 0 0.4rem' }}>Who are you, <span style={{ color: 'var(--accent-primary)' }}>{form.name}</span>?</h2>
            <p style={{ color: 'var(--text-muted)', marginBottom: '1.5rem', fontSize: '0.9rem' }}>Tailors difficulty and learning pace for you.</p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
              {ONBOARDING_SEGMENTS.map(s => (
                <div key={s.id}
                  onClick={() => setForm(f => ({ ...f, segment: s.id }))}
                  style={{
                    padding: '1rem 1.25rem', borderRadius: '12px', cursor: 'pointer',
                    border: `2px solid ${form.segment === s.id ? 'var(--accent-primary)' : 'var(--border-color)'}`,
                    background: form.segment === s.id ? 'rgba(0,240,255,0.08)' : 'var(--bg-tertiary)',
                    display: 'flex', alignItems: 'center', gap: '1rem', transition: 'all 0.2s'
                  }}>
                  <span style={{ fontSize: '1.6rem' }}>{s.icon}</span>
                  <div>
                    <div style={{ fontWeight: 600, fontSize: '0.95rem' }}>{s.label}</div>
                    <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>{s.desc}</div>
                  </div>
                  {form.segment === s.id && <span style={{ marginLeft: 'auto', color: 'var(--accent-primary)', fontSize: '1.1rem' }}>✓</span>}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Step 3 — Target role */}
        {step === 3 && (
          <div>
            <h2 style={{ margin: '0 0 0.4rem' }}>Your <span style={{ color: 'var(--accent-primary)' }}>target role</span>?</h2>
            <p style={{ color: 'var(--text-muted)', marginBottom: '1.5rem', fontSize: '0.9rem' }}>We build your skill gap analysis around this.</p>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
              {ONBOARDING_ROLES.map(r => (
                <div key={r.id}
                  onClick={() => setForm(f => ({ ...f, targetRole: r.id }))}
                  style={{
                    padding: '1rem', borderRadius: '12px', cursor: 'pointer', textAlign: 'center',
                    border: `2px solid ${form.targetRole === r.id ? 'var(--accent-primary)' : 'var(--border-color)'}`,
                    background: form.targetRole === r.id ? 'rgba(0,240,255,0.08)' : 'var(--bg-tertiary)',
                    transition: 'all 0.2s'
                  }}>
                  <div style={{ fontSize: '1.8rem', marginBottom: '0.4rem' }}>{r.icon}</div>
                  <div style={{ fontWeight: 600, fontSize: '0.85rem' }}>{r.id}</div>
                  <div style={{ color: 'var(--text-muted)', fontSize: '0.72rem', marginTop: '0.25rem' }}>{r.desc}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Step 4 — Time commitment */}
        {step === 4 && (
          <div>
            <h2 style={{ margin: '0 0 0.4rem' }}>Time <span style={{ color: 'var(--accent-primary)' }}>commitment</span></h2>
            <p style={{ color: 'var(--text-muted)', marginBottom: '1.5rem', fontSize: '0.9rem' }}>Calibrates your roadmap pace and task depth.</p>

            <label style={{ display: 'block', marginBottom: '0.6rem', fontSize: '0.85rem', color: 'var(--text-muted)' }}>Weekly hours available</label>
            <div style={{ display: 'flex', gap: '0.6rem', marginBottom: '1.5rem' }}>
              {ONBOARDING_HOURS.map(h => (
                <button key={h} onClick={() => setForm(f => ({ ...f, weeklyHours: h }))}
                  style={{
                    ...btnBase, flex: 1, padding: '0.6rem 0',
                    border: `2px solid ${form.weeklyHours === h ? 'var(--accent-primary)' : 'var(--border-color)'}`,
                    background: form.weeklyHours === h ? 'rgba(0,240,255,0.1)' : 'var(--bg-tertiary)',
                    color: 'var(--text-primary)'
                  }}>{h}h</button>
              ))}
            </div>

            <label style={{ display: 'block', marginBottom: '0.6rem', fontSize: '0.85rem', color: 'var(--text-muted)' }}>Target duration</label>
            <div style={{ display: 'flex', gap: '0.6rem', marginBottom: '2rem' }}>
              {ONBOARDING_DURATIONS.map(d => (
                <button key={d} onClick={() => setForm(f => ({ ...f, durationMonths: d }))}
                  style={{
                    ...btnBase, flex: 1, padding: '0.6rem 0',
                    border: `2px solid ${form.durationMonths === d ? 'var(--accent-secondary)' : 'var(--border-color)'}`,
                    background: form.durationMonths === d ? 'rgba(34,197,94,0.1)' : 'var(--bg-tertiary)',
                    color: 'var(--text-primary)'
                  }}>{d}mo</button>
              ))}
            </div>

            <div style={{
              padding: '1rem 1.25rem', borderRadius: '12px',
              background: 'rgba(0,240,255,0.06)', border: '1px solid rgba(0,240,255,0.2)',
              fontSize: '0.85rem', color: 'var(--text-muted)', lineHeight: 1.7
            }}>
              🎯 <strong style={{ color: 'var(--accent-primary)' }}>{form.name}</strong>{' '}·{' '}
              {ONBOARDING_SEGMENTS.find(s => s.id === form.segment)?.label}{' '}·{' '}
              {form.targetRole}{' '}·{' '}
              {form.weeklyHours}h/week · {form.durationMonths} month{form.durationMonths > 1 ? 's' : ''}
            </div>
          </div>
        )}

        {/* Step 5 — Resume + GitHub */}
        {step === 5 && (
          <div>
            <h2 style={{ margin: '0 0 0.4rem' }}>Upload your <span style={{ color: 'var(--accent-primary)' }}>profile</span></h2>
            <p style={{ color: 'var(--text-muted)', marginBottom: '1.5rem', fontSize: '0.9rem' }}>
              We'll extract your skills automatically. Both are optional — you can always do this later.
            </p>

            <div
              onClick={() => resumeRef.current?.click()}
              style={{
                border: `2px dashed ${form.resumeFile ? 'var(--accent-primary)' : 'var(--border-color)'}`,
                borderRadius: '12px', padding: '1.25rem', cursor: 'pointer', marginBottom: '1rem',
                background: form.resumeFile ? 'rgba(0,240,255,0.06)' : 'var(--bg-tertiary)',
                display: 'flex', alignItems: 'center', gap: '1rem', transition: 'all 0.2s'
              }}>
              <input type="file" ref={resumeRef} accept=".pdf" hidden
                onChange={e => setForm(f => ({ ...f, resumeFile: e.target.files?.[0] || null }))} />
              <span style={{ fontSize: '1.6rem' }}>📄</span>
              <div>
                <div style={{ fontWeight: 600, fontSize: '0.9rem' }}>
                  {form.resumeFile ? form.resumeFile.name : 'Upload Resume PDF'}
                </div>
                <div style={{ color: 'var(--text-muted)', fontSize: '0.78rem' }}>
                  {form.resumeFile ? '✓ Ready to scan' : 'Click to choose a PDF'}
                </div>
              </div>
              {form.resumeFile && (
                <span onClick={e => { e.stopPropagation(); setForm(f => ({ ...f, resumeFile: null })) }}
                  style={{ marginLeft: 'auto', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '1.1rem' }}>✕</span>
              )}
            </div>

            <label style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.85rem', color: 'var(--text-muted)' }}>GitHub Username</label>
            <div style={{ position: 'relative' }}>
              <span style={{ position: 'absolute', left: '0.85rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)', fontSize: '0.9rem' }}>@</span>
              <input
                className="custom-input"
                style={{ width: '100%', boxSizing: 'border-box', paddingLeft: '2rem' }}
                placeholder="e.g. octocat"
                value={form.githubUsername}
                onChange={e => setForm(f => ({ ...f, githubUsername: e.target.value }))}
              />
            </div>
            {!form.resumeFile && !form.githubUsername && (
              <p style={{ color: 'var(--text-muted)', fontSize: '0.78rem', marginTop: '1rem', textAlign: 'center' }}>
                You can skip this and add your profile later from the Profile Scan tab.
              </p>
            )}
          </div>
        )}



        {/* Navigation */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '2rem' }}>
          {step > 1
            ? <button onClick={() => setStep(s => s - 1)}
                style={{ background: 'none', border: '1px solid var(--border-color)', color: 'var(--text-muted)', padding: '0.6rem 1.2rem', borderRadius: '10px', cursor: 'pointer', fontSize: '0.9rem' }}>
                ← Back
              </button>
            : <button onClick={skip}
                style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '0.8rem', textDecoration: 'underline' }}>
                Skip setup
              </button>
          }
          {step < TOTAL
            ? <button onClick={() => setStep(s => s + 1)} disabled={!canNext()}
                style={{ ...btnBase, background: canNext() ? 'var(--accent-primary)' : 'var(--border-color)', color: canNext() ? '#000' : 'var(--text-muted)' }}>
                Continue →
              </button>
            : <button onClick={() => onComplete(form)}
                style={{ ...btnBase, background: 'var(--accent-primary)', color: '#000' }}>
                🚀 Start My Journey
              </button>
          }
        </div>
      </div>
    </div>
  )
}

const MASTERY_COLORS = {
  0: '#6B7280',
  1: '#8B5CF6',
  2: '#00F0FF',
  3: '#22C55E',
  4: '#F59E0B',
}

const CareerIntelligence = ({ metrics, masteryData, marketStats, setActiveTab }) => {
  const nextSkill = metrics?.next_priority_skill
  const totalJobs = marketStats?.total_jobs_processed
  const lastSyncedMs = marketStats?.refreshed_at
    ? Date.now() - new Date(marketStats.refreshed_at).getTime()
    : null
  const minsAgo = lastSyncedMs != null ? Math.floor(lastSyncedMs / 60000) : null

  return (
    <div style={{ marginBottom: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>

      {/* Row 1: Next Priority Skill + Market Snapshot */}
      <div style={{ display: 'grid', gridTemplateColumns: nextSkill ? '1fr 1fr' : '1fr', gap: '1rem' }}>

        {nextSkill && (
          <div
            onClick={() => setActiveTab('daily-quest')}
            style={{
              padding: '1.25rem',
              background: 'linear-gradient(135deg, rgba(0,240,255,0.08) 0%, rgba(0,240,255,0.03) 100%)',
              border: '1px solid rgba(0,240,255,0.3)', borderRadius: '14px',
              cursor: 'pointer', transition: 'all 0.2s',
              display: 'flex', flexDirection: 'column', gap: '0.4rem',
            }}
            onMouseEnter={e => { e.currentTarget.style.background = 'rgba(0,240,255,0.12)'; e.currentTarget.style.transform = 'translateY(-2px)' }}
            onMouseLeave={e => { e.currentTarget.style.background = 'linear-gradient(135deg, rgba(0,240,255,0.08) 0%, rgba(0,240,255,0.03) 100%)'; e.currentTarget.style.transform = 'none' }}
          >
            <div style={{ fontSize: '0.68rem', color: 'var(--accent-primary)', textTransform: 'uppercase', letterSpacing: '0.1em', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              🎯 AI Recommended Next Skill
              <span style={{ background: 'rgba(0,240,255,0.15)', border: '1px solid rgba(0,240,255,0.35)', borderRadius: '999px', padding: '0.1rem 0.5rem', fontSize: '0.6rem', letterSpacing: '0.06em' }}>AGENTIC LOOP</span>
            </div>
            <div style={{ fontWeight: 800, fontSize: '1.35rem', color: 'var(--text-primary)', lineHeight: 1.2 }}>{nextSkill}</div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', lineHeight: 1.5 }}>Re-ranked by market demand · gap severity · your mastery</div>
            <div style={{ marginTop: '0.3rem', fontSize: '0.78rem', color: 'var(--accent-primary)', fontWeight: 700 }}>→ Eat the Frog</div>
          </div>
        )}

        <div style={{
          padding: '1.25rem',
          background: 'linear-gradient(135deg, rgba(34,197,94,0.07) 0%, rgba(34,197,94,0.02) 100%)',
          border: '1px solid rgba(34,197,94,0.25)', borderRadius: '14px',
        }}>
          <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', fontWeight: 700, marginBottom: '0.75rem' }}>
            📡 Live Market Intelligence
          </div>
          {marketStats ? (
            <>
              <div style={{ fontWeight: 800, fontSize: '1.6rem', color: 'var(--accent-secondary)', lineHeight: 1 }}>
                {totalJobs?.toLocaleString()}
                <span style={{ fontSize: '0.78rem', fontWeight: 400, color: 'var(--text-muted)', marginLeft: '0.45rem' }}>jobs analyzed</span>
              </div>
              <div style={{ display: 'flex', gap: '0.6rem', marginTop: '0.65rem', flexWrap: 'wrap' }}>
                {[['RemoteOK', marketStats.sources?.remoteok, '#22C55E'], ['Indeed/LI', marketStats.sources?.jsearch, '#00F0FF'], ['Adzuna', marketStats.sources?.adzuna, '#F59E0B']].map(([label, count, color]) => (
                  <span key={label} style={{ fontSize: '0.7rem', fontWeight: 700, color, background: `${color}18`, padding: '0.2rem 0.55rem', borderRadius: '999px', border: `1px solid ${color}30` }}>
                    {label}: {count ?? 0}
                  </span>
                ))}
              </div>
              {minsAgo != null && (
                <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginTop: '0.55rem' }}>
                  Updated {minsAgo < 2 ? 'just now' : minsAgo < 60 ? `${minsAgo}m ago` : `${Math.floor(minsAgo / 60)}h ago`} · Weekly auto-refresh on
                </div>
              )}
            </>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem', color: 'var(--text-muted)', paddingTop: '0.5rem' }}>
              <Sparkles className="spin" size={14} /> Syncing live job market data…
            </div>
          )}
        </div>
      </div>

      {/* Row 2: Mastery Tracker */}
      {masteryData?.mastery_levels?.length > 0 && (
        <div style={{ padding: '1.25rem', background: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: '14px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
            <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', fontWeight: 700 }}>
              ⚡ Mastery Tracker <span style={{ color: 'var(--accent-primary)', marginLeft: '0.5rem', fontWeight: 400, textTransform: 'none', letterSpacing: 0 }}>— {masteryData.mastery_levels.length} skills tracked</span>
            </div>
            <span
              onClick={() => setActiveTab('stats')}
              style={{ fontSize: '0.75rem', color: 'var(--accent-primary)', cursor: 'pointer', fontWeight: 600 }}
            >View All →</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: '0.65rem' }}>
            {masteryData.mastery_levels.slice(0, 6).map(item => (
              <div key={item.skill} style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                <span style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-primary)', minWidth: '90px', maxWidth: '100px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.skill}</span>
                <div style={{ flex: 1, height: '5px', background: 'var(--bg-tertiary)', borderRadius: '999px', overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: `${(item.level / 4) * 100}%`, background: MASTERY_COLORS[item.level] || 'var(--accent-primary)', borderRadius: '999px', transition: 'width 0.6s ease' }} />
                </div>
                <span style={{ fontSize: '0.68rem', fontWeight: 700, color: MASTERY_COLORS[item.level], minWidth: '76px', textAlign: 'right' }}>{item.level_name}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

const Dashboard = ({ metrics, setActiveTab, userName, onSetName, masteryData, marketStats }) => {
  return (
    <>
      <WelcomeSection metrics={metrics} userName={userName} onSetName={onSetName} />
      <CareerIntelligence metrics={metrics} masteryData={masteryData} marketStats={marketStats} setActiveTab={setActiveTab} />
      <StatsGrid metrics={metrics} />
      <ActionGrid setActiveTab={setActiveTab} />
      <CommunitiesSection metrics={metrics} />
    </>
  )
}

const ProfileScan = ({ result, setResult }) => {
  const [file, setFile] = useState(null)
  const [username, setUsername] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const fileInputRef = useRef(null)

  const handleFileChange = (e) => {
    if (e.target.files && e.target.files[0]) {
      setFile(e.target.files[0])
    }
  }

  const handleAnalyze = async () => {
    if (!file && !username) {
      setError('Please upload a resume or enter a GitHub username.')
      return
    }

    setLoading(true)
    setError(null)
    const formData = new FormData()
    if (file) formData.append('resume', file)
    if (username) formData.append('github_username', username)

    try {
      const data = await analyzeProfile(formData)
      setResult(data)
    } catch (err) {
      console.error('Error analyzing profile:', err)
      setError(err.message || 'Failed to analyze profile. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  // Colors for the chart matching your theme
  const COLORS = ['#00F0FF', '#22C55E', '#F59E0B', '#8B5CF6', '#EC4899']

  return (
    <div className="scan-container">
      <div className="scan-header">
        <div className="scan-title">
          <ScanFace size={32} color="var(--accent-primary)" />
          <h2>Profile Analysis</h2>
        </div>
        <p className="scan-subtitle">Extract skills and insights from your resume and GitHub.</p>
      </div>

      {!result ? (
        <>
          <div className="input-grid">
            <div className="input-card">
              <div className="card-label">
                <FileText size={18} color="var(--accent-secondary)" />
                Resume PDF
              </div>
              <div
                className="upload-area"
                onClick={() => fileInputRef.current?.click()}
              >
                <input
                  type="file"
                  ref={fileInputRef}
                  onChange={handleFileChange}
                  hidden
                  accept=".pdf"
                />
                <Upload size={32} style={{ marginBottom: '1rem', opacity: 0.5 }} />
                <span>{file ? file.name : "Click to upload PDF"}</span>
              </div>
            </div>

            <div className="input-card">
              <div className="card-label">
                <Github size={18} color="var(--accent-primary)" />
                GitHub Username
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', height: '160px', justifyContent: 'center' }}>
                <input
                  type="text"
                  className="custom-input"
                  placeholder="e.g. octocat"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                />
                <p className="input-helper">Public repos will be analyzed for languages & activity.</p>
              </div>
            </div>
          </div>

          {error && (
            <p style={{ color: 'var(--accent-orange)', margin: '0.5rem 0 1rem', fontSize: '0.9rem' }}>⚠ {error}</p>
          )}
          <button
            className="analyze-btn"
            onClick={handleAnalyze}
            disabled={loading}
            style={{ opacity: loading ? 0.7 : 1, cursor: loading ? 'not-allowed' : 'pointer' }}
          >
            {loading ? <Sparkles className="spin" size={20} /> : <Sparkles size={20} />}
            {loading ? "Analyzing..." : "Analyze Profile"}
          </button>
        </>
      ) : (
        <div className="results-container">

          {/* ── Summary + Stats ── */}
          {result.summary && (
            <div className="result-card" style={{ borderLeft: '3px solid var(--accent-primary)' }}>
              <div style={{ fontSize: '0.72rem', color: 'var(--accent-primary)', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: '0.5rem' }}>AI SUMMARY</div>
              <p style={{ color: 'var(--text-secondary)', lineHeight: 1.7, margin: 0 }}>{result.summary}</p>
            </div>
          )}

          <div className="result-card">
            <h3>Profile Overview</h3>
            <div className="stats-grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))', gap: '0.75rem' }}>
              {[
                {
                  label: 'Experience',
                  value: result.years_of_experience != null ? `${result.years_of_experience} yrs` : '—',
                  color: 'var(--accent-primary)',
                  numeric: true,
                },
                {
                  label: 'Level',
                  value: result.experience_level
                    ? result.experience_level.charAt(0).toUpperCase() + result.experience_level.slice(1)
                    : '—',
                  color: 'var(--accent-secondary)',
                  numeric: false,
                },
                { label: 'Skills',         value: result.skill_ratings?.length || result.technical_skills?.length || 0, color: 'var(--accent-primary)',  numeric: true },
                { label: 'Projects',       value: result.projects?.length || 0,                                         color: 'var(--accent-orange)',   numeric: true },
                { label: 'GitHub Repos',   value: result.github_analysis?.repo_count || 0,                              color: 'var(--accent-primary)',  numeric: true },
                { label: 'Certifications', value: result.certifications?.length || 0,                                   color: '#8B5CF6',                numeric: true },
              ].map(s => (
                <div key={s.label} className="stat-card" style={{ textAlign: 'center' }}>
                  <span className="stat-label">{s.label}</span>
                  <div style={{
                    color: s.color,
                    fontWeight: 800,
                    fontSize: s.numeric ? '1.6rem' : '1rem',
                    lineHeight: 1.2,
                    marginTop: '0.3rem',
                    wordBreak: 'break-word',
                  }}>{s.value}</div>
                </div>
              ))}
            </div>
          </div>

          {/* ── Skill Ratings ── */}
          {result.skill_ratings?.length > 0 && (
            <div className="result-card">
              <h3>Skill Ratings</h3>
              {(['Expert','Advanced','Intermediate','Beginner']).map(level => {
                const skills = result.skill_ratings.filter(s => s.level === level)
                if (!skills.length) return null
                const levelColor = level === 'Expert' ? '#F59E0B' : level === 'Advanced' ? '#22C55E' : level === 'Intermediate' ? '#00F0FF' : '#8B5CF6'
                return (
                  <div key={level} style={{ marginBottom: '1.25rem' }}>
                    <div style={{ fontSize: '0.72rem', fontWeight: 700, color: levelColor, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: '0.6rem' }}>
                      {level} — {skills.length} skill{skills.length > 1 ? 's' : ''}
                    </div>
                    {skills.map((s, i) => (
                      <div key={i} style={{ marginBottom: '0.75rem' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.3rem' }}>
                          <span style={{ fontSize: '0.88rem', fontWeight: 600, color: 'var(--text-primary)' }}>{s.skill}</span>
                          <span style={{ fontSize: '0.8rem', fontWeight: 700, color: levelColor }}>{s.score}/100</span>
                        </div>
                        <div style={{ height: '6px', borderRadius: '999px', background: 'var(--bg-tertiary)', overflow: 'hidden' }}>
                          <div style={{ height: '100%', width: `${s.score}%`, background: levelColor, borderRadius: '999px', transition: 'width 0.6s ease' }} />
                        </div>
                        {s.evidence && (
                          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.25rem', fontStyle: 'italic' }}>{s.evidence}</div>
                        )}
                      </div>
                    ))}
                  </div>
                )
              })}
            </div>
          )}

          {/* ── Projects ── */}
          {result.projects?.length > 0 && (
            <div className="result-card">
              <h3>Projects ({result.projects.length})</h3>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '1rem', marginTop: '0.5rem' }}>
                {result.projects.map((proj, i) => {
                  const complexityColor = proj.complexity === 'Complex' ? '#F59E0B' : proj.complexity === 'Medium' ? '#00F0FF' : '#22C55E'
                  return (
                    <div key={i} style={{
                      background: 'var(--bg-secondary)', border: '1px solid var(--border-color)',
                      borderRadius: '12px', padding: '1rem', display: 'flex', flexDirection: 'column', gap: '0.5rem'
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '0.5rem' }}>
                        <div style={{ fontWeight: 700, fontSize: '0.95rem', color: 'var(--text-primary)' }}>{proj.name}</div>
                        {proj.complexity && (
                          <span style={{ fontSize: '0.68rem', fontWeight: 700, color: complexityColor, border: `1px solid ${complexityColor}`, borderRadius: '999px', padding: '0.15rem 0.5rem', whiteSpace: 'nowrap' }}>
                            {proj.complexity}
                          </span>
                        )}
                      </div>
                      <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', lineHeight: 1.6, margin: 0 }}>{proj.description}</p>
                      {proj.highlights?.length > 0 && (
                        <ul style={{ margin: 0, paddingLeft: '1rem', fontSize: '0.78rem', color: 'var(--text-secondary)', lineHeight: 1.7 }}>
                          {proj.highlights.map((h, hi) => <li key={hi}>{h}</li>)}
                        </ul>
                      )}
                      {proj.technologies?.length > 0 && (
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.35rem', marginTop: '0.25rem' }}>
                          {proj.technologies.map((t, ti) => (
                            <span key={ti} className="skill-tag tech" style={{ fontSize: '0.7rem', padding: '0.15rem 0.5rem' }}>{t}</span>
                          ))}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* ── GitHub Languages Chart ── */}
          {result.github_analysis?.language_breakdown && Object.keys(result.github_analysis.language_breakdown).length > 0 && (
            <div className="result-card">
              <h3>GitHub Languages</h3>
              {result.github_analysis.frameworks_detected?.length > 0 && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem', marginBottom: '1rem' }}>
                  {result.github_analysis.frameworks_detected.map((f, i) => (
                    <span key={i} className="skill-tag tech" style={{ fontSize: '0.75rem' }}>{f}</span>
                  ))}
                </div>
              )}
              <div style={{ height: '260px', width: '100%' }}>
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={Object.entries(result.github_analysis.language_breakdown).map(([name, value]) => ({ name, value }))}
                      cx="50%" cy="50%"
                      innerRadius={55} outerRadius={80}
                      paddingAngle={4} dataKey="value"
                    >
                      {Object.entries(result.github_analysis.language_breakdown).map((_, index) => (
                        <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} stroke="rgba(0,0,0,0)" />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={{ backgroundColor: '#1A1D24', border: '1px solid #2D3139', borderRadius: '8px' }} itemStyle={{ color: '#fff' }} />
                    <Legend />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* ── Strengths + Improvement Areas ── */}
          {(result.strengths?.length > 0 || result.improvement_areas?.length > 0) && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
              {result.strengths?.length > 0 && (
                <div className="result-card">
                  <h3 style={{ color: 'var(--accent-secondary)' }}>Strengths</h3>
                  <ul style={{ paddingLeft: '1.2rem', color: 'var(--text-muted)', lineHeight: 1.9, margin: 0 }}>
                    {result.strengths.map((s, i) => <li key={i}>{s}</li>)}
                  </ul>
                </div>
              )}
              {result.improvement_areas?.length > 0 && (
                <div className="result-card">
                  <h3 style={{ color: 'var(--accent-orange)' }}>Areas to Improve</h3>
                  <ul style={{ paddingLeft: '1.2rem', color: 'var(--text-muted)', lineHeight: 1.9, margin: 0 }}>
                    {result.improvement_areas.map((s, i) => <li key={i}>{s}</li>)}
                  </ul>
                </div>
              )}
            </div>
          )}

          {/* ── Education + Certifications ── */}
          {(result.education?.length > 0 || result.certifications?.length > 0) && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
              {result.education?.length > 0 && (
                <div className="result-card">
                  <h3>Education</h3>
                  <ul style={{ paddingLeft: '1.2rem', color: 'var(--text-muted)', lineHeight: 1.9, margin: 0 }}>
                    {result.education.map((e, i) => <li key={i}>{e}</li>)}
                  </ul>
                </div>
              )}
              {result.certifications?.length > 0 && (
                <div className="result-card">
                  <h3 style={{ color: '#8B5CF6' }}>Certifications</h3>
                  <ul style={{ paddingLeft: '1.2rem', color: 'var(--text-muted)', lineHeight: 1.9, margin: 0 }}>
                    {result.certifications.map((c, i) => <li key={i}>{c}</li>)}
                  </ul>
                </div>
              )}
            </div>
          )}

          {/* ── Soft Skills ── */}
          {result.soft_skills?.length > 0 && (
            <div className="result-card">
              <h3>Soft Skills</h3>
              <div className="skills-cloud">
                {result.soft_skills.map((skill, i) => (
                  <span key={i} className="skill-tag soft">{skill}</span>
                ))}
              </div>
            </div>
          )}

          {/* ── All Technical Skills (fallback if no ratings) ── */}
          {(!result.skill_ratings || result.skill_ratings.length === 0) && result.technical_skills?.length > 0 && (
            <div className="result-card">
              <h3>Technical Skills</h3>
              <div className="skills-cloud">
                {result.technical_skills.map((skill, i) => (
                  <span key={i} className="skill-tag tech">{skill}</span>
                ))}
              </div>
            </div>
          )}

          <button
            className="analyze-btn"
            onClick={() => setResult(null)}
            style={{ marginTop: '1rem', background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)' }}
          >
            Scan Another Profile
          </button>
        </div>
      )}
    </div>
  )
}

const Sidebar = ({ activeTab, setActiveTab, metrics }) => {
  const menuItems = [
    { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { id: 'profile-scan', label: 'Profile Scan', icon: ScanFace },
    { id: 'role-gap', label: 'Role Gap', icon: Target },
    { id: 'quest-map', label: 'Quest Map', icon: Map },
    { id: 'daily-quest', label: 'Eat the Frog', icon: Swords },
    { id: 'stats', label: 'Stats', icon: BarChart2 },
  ]

  // Progress toward NEXT community tier (500 / 1000 / 2500 / 5000)
  const TIERS = [500, 1000, 2500, 5000]
  const xp = metrics?.xp || 0
  const nextTier = TIERS.find(t => xp < t) || TIERS[TIERS.length - 1]
  const prevTier = TIERS[TIERS.indexOf(nextTier) - 1] || 0
  const xpProgress = Math.min(((xp - prevTier) / (nextTier - prevTier)) * 100, 100)

  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-logo">
          <Zap size={28} fill="currentColor" />
        </div>
        <div>
          CareerOS
          <span className="brand-subtitle">CO-PILOT</span>
        </div>
      </div>

      <div className="menu-label">MENU</div>
      <nav className="nav-menu">
        {menuItems.map((item) => (
          <div
            key={item.id}
            className={`nav-item ${activeTab === item.id ? 'active' : ''}`}
            onClick={() => setActiveTab(item.id)}
          >
            <item.icon size={20} />
            {item.label}
          </div>
        ))}
      </nav>

      <div className="sidebar-footer">
        <div className="rank-card">
          <div className="rank-info">
            <span className="rank-title">Rank</span>
            <span className="rank-value text-gradient">{metrics?.rank || 'Unranked'}</span>
          </div>
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${xpProgress}%` }}></div>
          </div>
          <div className="rank-info" style={{ marginTop: '8px', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
            <span>LVL {metrics?.level || 1}</span>
            <span>{xp}/{nextTier} XP</span>
          </div>
        </div>
      </div>
    </aside>
  )
}

const DashboardHeader = ({ metrics }) => {
  return (
    <header className="top-header">
      <div className="menu-trigger" style={{ display: 'none' }}>
        <Menu />
      </div>
      <div>
        {/* Breadcrumb or Title could go here */}
      </div>
      <div className="header-actions">
        <div className="fire-badge">
          <Flame size={16} fill="currentColor" />
          {metrics?.streak || 0}
        </div>
        <div className="xp-badge">
          <span style={{ fontSize: '0.8rem', fontWeight: 800 }}>XP</span>
          {metrics?.xp || 0} XP
        </div>
      </div>
    </header>
  )
}

const WelcomeSection = ({ metrics, userName, onSetName }) => {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(userName || '')
  const xpProgress = metrics ? (metrics.xp % 500) / 500 * 100 : 0

  const save = () => { if (draft.trim()) { onSetName(draft.trim()); setEditing(false) } }

  return (
    <section className="welcome-card">
      <div style={{ display: 'flex', alignItems: 'center', width: '100%' }}>
        <div className="welcome-badge">
          <div className="star-icon">
            <Award size={32} color="var(--text-muted)" />
          </div>
          <span style={{ fontSize: '0.7rem', marginTop: '0.5rem', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
            {metrics?.rank || 'unranked'}
          </span>
        </div>

        <div className="welcome-content" style={{ flex: 1 }}>
          {editing ? (
            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginBottom: '0.5rem' }}>
              <input
                autoFocus
                className="custom-input"
                style={{ height: '36px', fontSize: '1rem', maxWidth: '260px', padding: '0 0.75rem' }}
                value={draft}
                onChange={e => setDraft(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && save()}
                placeholder="Enter your name"
              />
              <button onClick={save} style={{ padding: '0.4rem 0.9rem', borderRadius: '8px', background: 'var(--accent-primary)', color: '#000', fontWeight: 700, border: 'none', cursor: 'pointer', fontSize: '0.85rem' }}>Save</button>
            </div>
          ) : (
            <h1 style={{ cursor: 'pointer' }} onClick={() => { setDraft(userName); setEditing(true) }}>
              Welcome, <span style={{ color: 'var(--accent-primary)' }}>{userName || 'Adventurer'}</span>
              <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginLeft: '0.5rem', fontWeight: 400 }}>✎</span>
            </h1>
          )}
          <p>Your career quest awaits. Level up by completing daily challenges.</p>

          <div className="level-info">
            <div className="level-text">
              <span>LVL {metrics?.level || 1} <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>NEXT LEVEL</span></span>
              <span style={{ color: 'var(--text-muted)' }}>{metrics ? metrics.xp % 500 : 0}/500</span>
            </div>
            <div className="progress-bar" style={{ height: '8px', background: 'var(--bg-primary)' }}>
              <div
                className="progress-fill"
                style={{
                  width: `${xpProgress}%`,
                  background: 'linear-gradient(90deg, var(--accent-secondary) 0%, var(--accent-primary) 100%)',
                  boxShadow: '0 0 10px rgba(0, 240, 255, 0.3)'
                }}
              ></div>
            </div>
          </div>
        </div>

        <div className="streak-circle" style={{ marginLeft: '2rem' }}>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            <Flame size={24} fill="currentColor" />
            <span>{metrics?.streak || 0}</span>
          </div>
        </div>
      </div>
    </section>
  )
}

const StatsGrid = ({ metrics }) => {
  const stats = [
    {
      label: 'Quests Done',
      value: metrics ? `${metrics.total_completed_tasks}/${metrics.total_assigned_tasks}` : '0/0',
      subtext: 'Lifetime total',
      icon: Award,
      color: 'var(--accent-secondary)',
      trend: true
    },
    {
      label: 'Rank Tier',
      value: metrics?.rank || 'Unranked',
      subtext: 'Global standing',
      icon: Target,
      color: 'var(--accent-primary)',
      trend: true
    },
    {
      label: 'Day Streak',
      value: metrics ? `${metrics.streak} 🔥` : '0 🔥',
      subtext: 'Consistency',
      icon: Flame,
      color: 'var(--accent-orange)',
      trend: true
    },
    {
      label: 'Execution',
      value: metrics?.execution_score.toFixed(0) || 0,
      subtext: 'Accuracy score',
      icon: TrendingUp,
      color: '#8B5CF6',
      trend: true
    },
  ]

  return (
    <div className="stats-grid">
      {stats.map((stat, index) => (
        <div key={index} className="stat-card">
          <div className="trend-indicator">▲</div>
          <div className="stat-icon" style={{ color: stat.color, backgroundColor: `${stat.color}15` }}>
            <stat.icon size={20} />
          </div>
          <div className="stat-value">{stat.value}</div>
          <span className="stat-label">{stat.label}</span>
          <p className="stat-subtext">{stat.subtext}</p>
        </div>
      ))}
    </div>
  )
}

const ActionGrid = ({ setActiveTab }) => {
  return (
    <div className="action-grid">
      <div className="action-card" onClick={() => setActiveTab('daily-quest')} style={{ cursor: 'pointer' }}>
        <div className="action-left">
          <div className="action-icon-box" style={{ background: 'rgba(34, 197, 94, 0.1)', color: 'var(--accent-secondary)' }}>
            <Swords size={24} />
          </div>
          <div>
            <h3 style={{ fontSize: '1rem' }}>Eat the Frog</h3>
            <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>+5–20 XP available</span>
          </div>
        </div>
        <ChevronRight size={20} color="var(--text-muted)" />
      </div>

      <div className="action-card" onClick={() => setActiveTab('profile-scan')} style={{ cursor: 'pointer' }}>
        <div className="action-left">
          <div className="action-icon-box" style={{ background: 'rgba(139, 92, 246, 0.1)', color: '#8B5CF6' }}>
            <ScanFace size={24} />
          </div>
          <div>
            <h3 style={{ fontSize: '1rem' }}>Scan Profile</h3>
            <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Unlock skill tree</span>
          </div>
        </div>
        <ChevronRight size={20} color="var(--text-muted)" />
      </div>
    </div>
  )
}

const CommunitiesSection = ({ metrics }) => {
  const currentXP = metrics?.xp || 0

  const communities = [
    {
      id: 'beginner',
      name: 'Beginner Community',
      threshold: 500,
      description: 'Start your journey with other builders.',
      tag: 'LEVEL 1+',
      color: 'var(--accent-secondary)',
      discord: 'https://discord.gg/WMjyddhq'
    },
    {
      id: 'intermediate',
      name: 'Intermediate Community',
      threshold: 1000,
      description: 'Step up to more advanced challenges.',
      tag: 'LEVEL 5+',
      color: 'var(--accent-primary)',
      discord: 'https://discord.gg/WMjyddhq'
    },
    {
      id: 'advanced',
      name: 'Advanced Community',
      threshold: 2500,
      description: 'Connect with seasoned professionals.',
      tag: 'LEVEL 10+',
      color: '#8B5CF6',
      discord: 'https://discord.gg/WMjyddhq'
    },
    {
      id: 'expert',
      name: 'Expert Community',
      threshold: 5000,
      description: 'Exclusive elite-only space.',
      tag: 'ELITE',
      color: 'gold',
      discord: 'https://discord.gg/WMjyddhq'
    }
  ]

  const joinCommunity = (comm) => {
    if (currentXP >= comm.threshold) {
      window.open(comm.discord, '_blank')
    }
  }

  const unlockedCount = communities.filter(c => currentXP >= c.threshold).length

  return (
    <div style={{ marginTop: '2.5rem' }}>
      <div className="section-title">
        <Users size={20} color="var(--accent-primary)" />
        <h3>Guilds & Communities</h3>
        <span style={{ marginLeft: 'auto', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
          {unlockedCount}/{communities.length} joined
        </span>
      </div>

      <div className="achievement-grid" style={{ marginBottom: '2rem' }}>
        {communities.map((comm) => {
          const isUnlocked = currentXP >= comm.threshold
          return (
            <div
              key={comm.id}
              className={`achievement-card ${isUnlocked ? 'unlocked' : ''}`}
              onClick={() => joinCommunity(comm)}
              style={{
                borderColor: isUnlocked ? comm.color : 'var(--border-color)',
                opacity: isUnlocked ? 1 : 0.4,
                position: 'relative',
                cursor: isUnlocked ? 'pointer' : 'default',
                transition: 'all 0.3s ease'
              }}
            >
              <div className="achievement-icon" style={{
                background: isUnlocked ? `${comm.color}15` : 'var(--bg-primary)',
                color: isUnlocked ? comm.color : 'var(--text-muted)'
              }}>
                <Users size={20} />
              </div>
              <div className="achievement-info">
                <div style={{ display: 'flex', alignItems: 'center' }}>
                  <h4 style={{ color: isUnlocked ? 'var(--text-primary)' : 'var(--text-muted)' }}>{comm.name}</h4>
                  <span className="achievement-tag" style={{
                    color: isUnlocked ? comm.color : 'inherit',
                    borderColor: isUnlocked ? comm.color : 'transparent'
                  }}>
                    {comm.tag}
                  </span>
                </div>
                <p className="achievement-desc">
                  {isUnlocked ? comm.description : `Unlock at ${comm.threshold} XP`}
                </p>
              </div>
              {isUnlocked ? (
                <ExternalLink size={14} style={{ position: 'absolute', top: '1rem', right: '1rem', color: comm.color }} />
              ) : (
                <Lock size={14} style={{ position: 'absolute', top: '1rem', right: '1rem', color: 'var(--text-muted)' }} />
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

const RoleGap = ({ userSkills, userAddedSkills = [], onAddSkill, onRemoveSkill, gapResult, setGapResult, selectedRole, setSelectedRole, marketStats, setMarketStats }) => {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [skillInput, setSkillInput] = useState('')

  const handleAddSkill = () => {
    const trimmed = skillInput.trim()
    if (trimmed && onAddSkill) {
      onAddSkill(trimmed)
      setSkillInput('')
    }
  }
  const [impactResult, setImpactResult] = useState(null)
  const [marketRefreshing, setMarketRefreshing] = useState(false)
  const [marketError, setMarketError] = useState(null)

  const handleMarketRefresh = async () => {
    setMarketRefreshing(true)
    setMarketError(null)
    try {
      const data = await refreshMarketData()
      const stats = { ...data, refreshed_at: new Date().toISOString() }
      if (setMarketStats) setMarketStats(stats)
    } catch (e) {
      setMarketError('Refresh failed: ' + (e.message || 'Unknown error'))
    } finally {
      setMarketRefreshing(false)
    }
  }

  const roles = [
    "Frontend Developer",
    "Backend Developer",
    "Full Stack Developer",
    "Data Analyst",
    "Data Scientist",
    "Machine Learning Engineer",
    "DevOps Engineer",
    "Cloud Engineer",
    "Mobile Developer",
    "AI/ML Research Engineer",
    "Site Reliability Engineer",
    "Product Manager",
  ]

  const handleAnalyze = async () => {
    if (!selectedRole) return

    setLoading(true)
    setError(null)
    setImpactResult(null)
    const allSkills = [...new Set([...userSkills])]
    try {
      const response = await fetch(`${BASE_URL}/analyze-role`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_skills: allSkills,
          selected_role: selectedRole
        })
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const data = await response.json()
      setGapResult(data)

      // Fire skill impact in background — doesn't block the gap result
      getSkillImpact({ user_skills: allSkills, target_role: selectedRole, user_id: 'user_1' })
        .then(setImpactResult)
        .catch(() => {}) // silent — impact scores are bonus data
    } catch (e) {
      console.error(e)
      setError(e.message || 'Gap analysis failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="scan-container">
      <div className="scan-header">
        <div className="scan-title">
          <Target size={32} color="var(--accent-secondary)" />
          <h2>Role Gap Analysis</h2>
        </div>
        <p className="scan-subtitle">Compare your skills against your target role using live job market data.</p>
      </div>

      {/* ── Live Market Data Sources Banner ── */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap',
        padding: '0.85rem 1.1rem', marginBottom: '1.5rem',
        background: 'rgba(0,240,255,0.04)', borderRadius: '10px',
        border: '1px solid rgba(0,240,255,0.12)'
      }}>
        <TrendingUp size={15} color="var(--accent-primary)" style={{ flexShrink: 0 }} />
        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, letterSpacing: '0.05em' }}>LIVE DATA SOURCES</span>
        {[
          { label: 'RemoteOK', count: marketStats?.sources?.remoteok, color: '#22C55E' },
          { label: 'Indeed / LinkedIn', count: marketStats?.sources?.jsearch, color: '#00F0FF' },
          { label: 'Adzuna', count: marketStats?.sources?.adzuna, color: '#F59E0B' },
        ].map(src => (
          <span key={src.label} style={{
            display: 'inline-flex', alignItems: 'center', gap: '0.35rem',
            padding: '0.2rem 0.6rem', borderRadius: '999px',
            background: `${src.color}18`, border: `1px solid ${src.color}44`,
            fontSize: '0.72rem', fontWeight: 700, color: src.color
          }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: src.color, display: 'inline-block' }} />
            {src.label}{src.count != null ? `: ${src.count} jobs` : ''}
          </span>
        ))}
        {marketStats?.refreshed_at && (
          <span style={{ marginLeft: 'auto', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
            Last synced: {new Date(marketStats.refreshed_at).toLocaleTimeString()}
          </span>
        )}
        {marketStats?.total_jobs_processed != null && (
          <span style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--accent-secondary)' }}>
            {marketStats.total_jobs_processed} jobs analysed
          </span>
        )}
        <button
          onClick={handleMarketRefresh}
          disabled={marketRefreshing}
          style={{
            marginLeft: marketStats ? '0' : 'auto',
            padding: '0.3rem 0.8rem', borderRadius: '6px', fontSize: '0.72rem', fontWeight: 700,
            border: '1px solid var(--accent-primary)', background: 'transparent',
            color: 'var(--accent-primary)', cursor: marketRefreshing ? 'not-allowed' : 'pointer',
            display: 'flex', alignItems: 'center', gap: '0.4rem', opacity: marketRefreshing ? 0.6 : 1,
            transition: 'background 0.2s'
          }}
        >
          {marketRefreshing ? <Sparkles className="spin" size={12} /> : <TrendingUp size={12} />}
          {marketRefreshing ? 'Syncing...' : 'Sync Now'}
        </button>
        {marketError && <span style={{ fontSize: '0.7rem', color: 'var(--accent-orange)' }}>⚠ {marketError}</span>}
      </div>

      <div style={{ marginBottom: '2rem' }}>
        <select
          className="custom-input"
          style={{ height: '50px', fontSize: '1rem', cursor: 'pointer' }}
          value={selectedRole}
          onChange={(e) => setSelectedRole(e.target.value)}
        >
          <option value="">Select target role</option>
          {roles.map(r => <option key={r} value={r}>{r}</option>)}
        </select>

        {error && (
          <p style={{ color: 'var(--accent-orange)', marginTop: '0.5rem', fontSize: '0.9rem' }}>⚠ {error}</p>
        )}

        {/* ── Manually Add Skills ── */}
        <div style={{ marginTop: '1.25rem' }}>
          <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', fontWeight: 600, letterSpacing: '0.05em', textTransform: 'uppercase', marginBottom: '0.6rem' }}>
            Add Your Skills Manually
          </div>
          <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.75rem' }}>
            <input
              className="custom-input"
              style={{ flex: 1, height: '42px', padding: '0 0.9rem', fontSize: '0.9rem' }}
              placeholder="e.g. FastAPI, Redis, Terraform…"
              value={skillInput}
              onChange={(e) => setSkillInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); handleAddSkill() } }}
            />
            <button
              onClick={handleAddSkill}
              disabled={!skillInput.trim()}
              style={{
                height: '42px', padding: '0 1rem', borderRadius: '8px', fontWeight: 700, fontSize: '0.88rem',
                border: '1px solid var(--accent-primary)', background: 'rgba(0,240,255,0.08)',
                color: 'var(--accent-primary)', cursor: skillInput.trim() ? 'pointer' : 'not-allowed',
                opacity: skillInput.trim() ? 1 : 0.4, transition: 'all 0.2s',
              }}
            >+ Add</button>
          </div>
          {userAddedSkills.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.45rem' }}>
              {userAddedSkills.map(s => (
                <span key={s} style={{
                  display: 'inline-flex', alignItems: 'center', gap: '0.35rem',
                  padding: '0.2rem 0.7rem', borderRadius: '999px', fontSize: '0.8rem',
                  background: 'rgba(0,240,255,0.08)', border: '1px solid rgba(0,240,255,0.25)',
                  color: 'var(--accent-primary)',
                }}>
                  {s}
                  <span
                    onClick={() => onRemoveSkill && onRemoveSkill(s)}
                    style={{ cursor: 'pointer', opacity: 0.6, fontWeight: 700, lineHeight: 1 }}
                  >×</span>
                </span>
              ))}
            </div>
          )}
        </div>

        <button
          className="analyze-btn"
          style={{ marginTop: '1rem', backgroundColor: selectedRole ? 'var(--accent-secondary)' : 'var(--bg-tertiary)', color: selectedRole ? 'var(--bg-primary)' : 'var(--text-muted)' }}
          onClick={handleAnalyze}
          disabled={!selectedRole || loading}
        >
          {loading ? <Sparkles className="spin" size={20} /> : <Target size={20} />}
          {loading ? "Analyzing..." : "Analyze Gap"}
        </button>
      </div>

      {gapResult && (
        <div className="results-container">
          <div className="result-card" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '1.5rem' }}>
            <div style={{ flex: 1 }}>
              <span className="stat-label">Role Alignment Score</span>
              <div style={{ fontSize: '3.2rem', fontWeight: 800, color: gapResult.alignment_score > 70 ? 'var(--accent-secondary)' : gapResult.alignment_score > 40 ? 'var(--accent-orange)' : '#EF4444', lineHeight: 1 }}>
                {gapResult.alignment_score}%
              </div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '0.4rem' }}>
                {gapResult.alignment_score > 70 ? '🟢 Strong match — ready to apply' : gapResult.alignment_score > 40 ? '🟡 Moderate — close a few gaps first' : '🔴 Significant skill gaps remaining'}
              </div>
            </div>
            <div style={{ position: 'relative', width: '110px', height: '110px', flexShrink: 0 }}>
              <svg width="110" height="110" style={{ transform: 'rotate(-90deg)' }}>
                <circle cx="55" cy="55" r="44" fill="none" stroke="var(--bg-tertiary)" strokeWidth="10" />
                <circle
                  cx="55" cy="55" r="44"
                  fill="none"
                  stroke={gapResult.alignment_score > 70 ? 'var(--accent-secondary)' : gapResult.alignment_score > 40 ? 'var(--accent-orange)' : '#EF4444'}
                  strokeWidth="10"
                  strokeLinecap="round"
                  strokeDasharray={`${2 * Math.PI * 44}`}
                  strokeDashoffset={`${2 * Math.PI * 44 * (1 - gapResult.alignment_score / 100)}`}
                  style={{ transition: 'stroke-dashoffset 0.8s ease' }}
                />
              </svg>
              <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
                <span style={{ fontWeight: 800, fontSize: '1.1rem', color: 'var(--text-primary)' }}>{gapResult.alignment_score}%</span>
                <span style={{ fontSize: '0.6rem', color: 'var(--text-muted)', textTransform: 'uppercase' }}>match</span>
              </div>
            </div>
          </div>

          {gapResult.missing_skills.length > 0 && (
            <div className="result-card">
              <h3>Priority Skills to Learn</h3>
              <div style={{ width: '100%', height: 300 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    layout="vertical"
                    data={gapResult.missing_skills.slice(0, 5)}
                    margin={{ top: 20, right: 30, left: 40, bottom: 5 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#2D3139" />
                    <XAxis type="number" stroke="#6B7280" hide />
                    <YAxis
                      dataKey="skill"
                      type="category"
                      stroke="#9CA3AF"
                      width={100}
                      tick={{ fill: '#9CA3AF', fontSize: 12 }}
                    />
                    <Tooltip
                      contentStyle={{ backgroundColor: '#1A1D24', border: '1px solid #2D3139', borderRadius: '8px' }}
                      itemStyle={{ color: '#fff' }}
                      cursor={{ fill: 'rgba(255,255,255,0.05)' }}
                    />
                    <Bar dataKey="importance" fill="#F59E0B" radius={[0, 4, 4, 0]} name="Impact" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          <div className="result-card">
              <h3>Missing Skills</h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
              {gapResult.missing_skills.length === 0 ? (
                <p style={{ color: 'var(--text-muted)' }}>No missing skills found! You are a perfect match.</p>
              ) : (
                gapResult.missing_skills.map((item, i) => {
                  const maxImportance = Math.max(...gapResult.missing_skills.map(s => s.importance), 1)
                  const barPct = Math.round((item.importance / maxImportance) * 100)
                  const iTop = i === 0
                  return (
                    <div key={i} style={{
                      padding: '0.9rem 1rem',
                      background: iTop ? 'rgba(245,158,11,0.06)' : 'var(--bg-primary)',
                      borderRadius: '10px',
                      border: iTop ? '1px solid rgba(245,158,11,0.25)' : '1px solid var(--border-color)',
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.4rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                          {iTop && <span style={{ fontSize: '0.65rem', fontWeight: 700, color: '#F59E0B', border: '1px solid #F59E0B', borderRadius: '999px', padding: '0.1rem 0.45rem', textTransform: 'uppercase' }}>Top Priority</span>}
                          <div style={{ fontWeight: 700, color: 'var(--text-primary)', fontSize: '0.95rem' }}>{item.skill}</div>
                        </div>
                        <div style={{ fontSize: '0.78rem', fontWeight: 700, color: 'var(--accent-orange)', background: 'rgba(245,158,11,0.1)', padding: '0.2rem 0.55rem', borderRadius: '6px' }}>
                          Impact {item.importance}
                        </div>
                      </div>
                      <div style={{ height: '4px', background: 'var(--bg-tertiary)', borderRadius: '999px', overflow: 'hidden', marginBottom: '0.45rem' }}>
                        <div style={{ height: '100%', width: `${barPct}%`, background: iTop ? '#F59E0B' : 'var(--accent-primary)', borderRadius: '999px', transition: 'width 0.6s ease' }} />
                      </div>
                      <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', lineHeight: 1.5 }}>{item.why_this_skill_matters}</div>
                    </div>
                  )
                })
              )}
            </div>
          </div>

          {/* ── Market Impact Scores (loaded async) ── */}
          {impactResult ? (
            <div className="result-card fade-in">
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1.25rem' }}>
                <Cpu size={18} color="var(--accent-primary)" />
                <h3 style={{ margin: 0 }}>Market Impact Scores</h3>
                <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginLeft: 'auto' }}>
                  demand × mastery × relevance
                </span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
                {impactResult.ranked_skills?.slice(0, 8).map((item, i) => (
                  <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                    <span style={{
                      minWidth: '20px', fontSize: '0.7rem', fontWeight: 700,
                      color: i === 0 ? 'var(--accent-primary)' : 'var(--text-muted)',
                      textAlign: 'right'
                    }}>#{item.priority_rank}</span>
                    <span style={{ flex: 1, fontWeight: 500, fontSize: '0.9rem' }}>{item.skill}</span>
                    <div style={{ width: '120px', height: '4px', background: 'var(--bg-tertiary)', borderRadius: '2px', overflow: 'hidden' }}>
                      <div style={{
                        height: '100%',
                        width: `${item.impact_score}%`,
                        background: 'linear-gradient(90deg, var(--accent-secondary), var(--accent-primary))',
                        borderRadius: '2px',
                      }} />
                    </div>
                    <span style={{ minWidth: '32px', textAlign: 'right', fontWeight: 700, fontSize: '0.85rem', color: 'var(--accent-orange)' }}>
                      {item.impact_score?.toFixed(0)}
                    </span>
                  </div>
                ))}
              </div>
              {impactResult.top_priority && (
                <div style={{ marginTop: '1rem', padding: '0.75rem', background: 'rgba(0,240,255,0.05)', borderRadius: '8px', border: '1px solid rgba(0,240,255,0.15)' }}>
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>TOP PRIORITY → </span>
                  <span style={{ fontWeight: 700, color: 'var(--accent-primary)' }}>{impactResult.top_priority}</span>
                </div>
              )}
            </div>
          ) : gapResult && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', padding: '1rem', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
              <Sparkles className="spin" size={16} />
              Computing market impact scores...
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const RESOURCE_META = {
  youtube:  { icon: '▶', label: 'YouTube',  color: '#FF0000', bg: 'rgba(255,0,0,0.08)' },
  docs:     { icon: '📄', label: 'Docs',     color: '#00F0FF', bg: 'rgba(0,240,255,0.08)' },
  article:  { icon: '📝', label: 'Article',  color: '#F59E0B', bg: 'rgba(245,158,11,0.08)' },
  practice: { icon: '💻', label: 'Practice', color: '#22C55E', bg: 'rgba(34,197,94,0.08)' },
  course:   { icon: '🎓', label: 'Course',   color: '#8B5CF6', bg: 'rgba(139,92,246,0.08)' },
}

const QuestMap = ({ gapResult, userSkills, selectedRole }) => {
  const [loading, setLoading] = useState(false)
  const [roadmap, setRoadmap] = useState(null)
  const [error, setError] = useState(null)

  // Resources drawer state
  const [drawer, setDrawer] = useState(null)   // { task, skill, day }
  const [resources, setResources] = useState([])
  const [repos, setRepos] = useState([])
  const [loadingRes, setLoadingRes] = useState(false)
  const [resError, setResError] = useState(null)

  const handleGenerate = async () => {
    if (!gapResult || !selectedRole) return
    setLoading(true)
    setError(null)
    try {
      const data = await generateCareerPlan({ user_skills: userSkills, selected_role: selectedRole })
      setRoadmap(data)
    } catch (err) {
      setError(err.message || 'Failed to generate career plan. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const openDrawer = async (day, weekFocus) => {
    setDrawer({ task: day.task, description: day.description, skill: weekFocus, day: day.day })
    setResources([])
    setRepos([])
    setResError(null)
    setLoadingRes(true)
    try {
      const data = await getLearningResources(day.task, weekFocus, selectedRole || '')
      setResources(data.resources || [])
      setRepos(data.repos || [])
    } catch (e) {
      setResError('Could not load resources. Try again.')
    } finally {
      setLoadingRes(false)
    }
  }

  const closeDrawer = () => { setDrawer(null); setResources([]); setRepos([]) }

  if (!gapResult) {
    return (
      <div className="scan-container">
        <div className="scan-header">
          <div className="scan-title">
            <Map size={32} color="var(--accent-primary)" />
            <h2>Quest Map</h2>
          </div>
          <p className="scan-subtitle">Complete the Role Gap Analysis first to unlock your quest map.</p>
        </div>
      </div>
    )
  }

  return (
    <div className="scan-container">
      <div className="scan-header">
        <div className="scan-title">
          <Map size={32} color="var(--accent-primary)" />
          <h2>Quest Map</h2>
        </div>
        <p className="scan-subtitle">Your personalized 30-day adventure to skill mastery. Click any topic to get learning resources.</p>
      </div>

      {/* ── Resources Drawer (overlay) ── */}
      {drawer && (
        <div
          onClick={closeDrawer}
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.65)',
            zIndex: 1000, display: 'flex', justifyContent: 'flex-end',
            backdropFilter: 'blur(4px)',
          }}
        >
          <div
            onClick={e => e.stopPropagation()}
            style={{
              width: 'min(480px, 100vw)', height: '100%', background: 'var(--bg-secondary)',
              borderLeft: '1px solid var(--border-color)', display: 'flex', flexDirection: 'column',
              animation: 'slideInRight 0.22s ease',
              overflowY: 'auto',
            }}
          >
            {/* Header */}
            <div style={{
              padding: '1.5rem 1.5rem 1rem', borderBottom: '1px solid var(--border-color)',
              position: 'sticky', top: 0, background: 'var(--bg-secondary)', zIndex: 1,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem' }}>
                <div>
                  <div style={{ fontSize: '0.7rem', color: 'var(--accent-primary)', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: '0.4rem' }}>
                    Day {drawer.day} · {drawer.skill}
                  </div>
                  <h3 style={{ margin: 0, fontSize: '1rem', lineHeight: 1.4, color: 'var(--text-primary)' }}>{drawer.task}</h3>
                  {drawer.description && (
                    <p style={{ margin: '0.4rem 0 0', fontSize: '0.82rem', color: 'var(--text-muted)', lineHeight: 1.6 }}>{drawer.description}</p>
                  )}
                </div>
                <button
                  onClick={closeDrawer}
                  style={{
                    flexShrink: 0, background: 'var(--bg-tertiary)', border: 'none',
                    borderRadius: '8px', width: '32px', height: '32px', cursor: 'pointer',
                    color: 'var(--text-muted)', fontSize: '1.1rem', display: 'flex',
                    alignItems: 'center', justifyContent: 'center',
                  }}
                >✕</button>
              </div>
            </div>

            {/* Resource list */}
            <div style={{ padding: '1.25rem 1.5rem', flex: 1 }}>
              {loadingRes ? (
                <div style={{ textAlign: 'center', padding: '3rem 0' }}>
                  <Sparkles className="spin" size={28} color="var(--accent-primary)" />
                  <p style={{ color: 'var(--text-muted)', marginTop: '0.75rem', fontSize: '0.88rem' }}>Finding best resources…</p>
                </div>
              ) : resError ? (
                <p style={{ color: 'var(--accent-orange)', fontSize: '0.9rem' }}>⚠ {resError}</p>
              ) : resources.length === 0 ? (
                <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>No resources found.</p>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
                  {resources.map((r, i) => {
                    const meta = RESOURCE_META[r.type] || RESOURCE_META.article
                    return (
                      <a
                        key={i}
                        href={r.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{
                          display: 'flex', gap: '0.85rem', alignItems: 'flex-start',
                          background: meta.bg, border: `1px solid ${meta.color}30`,
                          borderRadius: '12px', padding: '0.9rem 1rem',
                          textDecoration: 'none', transition: 'transform 0.15s, box-shadow 0.15s',
                        }}
                        onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-1px)'; e.currentTarget.style.boxShadow = `0 4px 16px ${meta.color}20` }}
                        onMouseLeave={e => { e.currentTarget.style.transform = 'none'; e.currentTarget.style.boxShadow = 'none' }}
                      >
                        <div style={{
                          flexShrink: 0, width: '36px', height: '36px', borderRadius: '8px',
                          background: `${meta.color}18`, display: 'flex', alignItems: 'center',
                          justifyContent: 'center', fontSize: '1rem',
                        }}>
                          {meta.icon}
                        </div>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.2rem', flexWrap: 'wrap' }}>
                            <span style={{ fontWeight: 700, fontSize: '0.88rem', color: 'var(--text-primary)' }}>{r.title}</span>
                            <span style={{
                              fontSize: '0.65rem', fontWeight: 700, color: meta.color,
                              border: `1px solid ${meta.color}`, borderRadius: '999px',
                              padding: '0.1rem 0.45rem', letterSpacing: '0.05em', textTransform: 'uppercase',
                            }}>{meta.label}</span>
                          </div>
                          <p style={{ margin: 0, fontSize: '0.78rem', color: 'var(--text-muted)', lineHeight: 1.5 }}>{r.description}</p>
                          <div style={{ fontSize: '0.7rem', color: meta.color, marginTop: '0.3rem', opacity: 0.7, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {r.url}
                          </div>
                        </div>
                        <ExternalLink size={13} style={{ flexShrink: 0, color: 'var(--text-muted)', marginTop: '0.15rem' }} />
                      </a>
                    )
                  })}
                </div>
              )}

              {/* ── GitHub Project Repos ── */}
              {!loadingRes && repos.length > 0 && (
                <div style={{ marginTop: '1.75rem' }}>
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: '0.5rem',
                    fontSize: '0.7rem', fontWeight: 700, color: 'var(--text-muted)',
                    letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: '0.75rem',
                  }}>
                    <Github size={13} />
                    Project Ideas — GitHub Repos to Study or Fork
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
                    {repos.map((repo, i) => (
                      <a
                        key={i}
                        href={repo.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{
                          display: 'flex', gap: '0.75rem', alignItems: 'flex-start',
                          background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)',
                          borderRadius: '12px', padding: '0.85rem 1rem',
                          textDecoration: 'none', transition: 'border-color 0.15s, background 0.15s',
                        }}
                        onMouseEnter={e => { e.currentTarget.style.borderColor = 'rgba(255,255,255,0.18)'; e.currentTarget.style.background = 'rgba(255,255,255,0.06)' }}
                        onMouseLeave={e => { e.currentTarget.style.borderColor = 'rgba(255,255,255,0.07)'; e.currentTarget.style.background = 'rgba(255,255,255,0.03)' }}
                      >
                        <div style={{
                          flexShrink: 0, width: '34px', height: '34px', borderRadius: '8px',
                          background: 'rgba(255,255,255,0.06)', display: 'flex',
                          alignItems: 'center', justifyContent: 'center',
                        }}>
                          <Github size={16} color="var(--text-secondary)" />
                        </div>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.2rem', flexWrap: 'wrap' }}>
                            <span style={{ fontWeight: 700, fontSize: '0.85rem', color: 'var(--accent-primary)', fontFamily: 'monospace' }}>{repo.name}</span>
                            {repo.stars && repo.stars !== '—' && (
                              <span style={{ fontSize: '0.7rem', color: '#F59E0B', fontWeight: 600 }}>⭐ {repo.stars}</span>
                            )}
                          </div>
                          <p style={{ margin: 0, fontSize: '0.78rem', color: 'var(--text-muted)', lineHeight: 1.5 }}>{repo.description}</p>
                          {repo.why && (
                            <p style={{ margin: '0.3rem 0 0', fontSize: '0.74rem', color: 'var(--accent-secondary)', lineHeight: 1.4, fontStyle: 'italic' }}>💡 {repo.why}</p>
                          )}
                        </div>
                        <ExternalLink size={12} style={{ flexShrink: 0, color: 'var(--text-muted)', marginTop: '0.2rem' }} />
                      </a>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {!roadmap ? (
        <div className="result-card" style={{ textAlign: 'center', padding: '4rem 2rem' }}>
          <div style={{
            width: '80px', height: '80px', background: 'var(--bg-tertiary)',
            borderRadius: '20px', display: 'flex', alignItems: 'center', justifyContent: 'center',
            margin: '0 auto 1.5rem auto'
          }}>
            <Map size={40} color="var(--accent-primary)" />
          </div>
          <h3 style={{ marginBottom: '0.5rem' }}>Generate Quest Map</h3>
          <p style={{ color: 'var(--text-muted)', marginBottom: '2rem' }}>
            Create a personalized plan to conquer your missing skills: {gapResult.missing_skills.slice(0, 3).map(s => s.skill).join(', ')}...
          </p>
          {error && <p style={{ color: 'var(--accent-orange)', marginBottom: '1rem', fontSize: '0.9rem' }}>⚠ {error}</p>}
          <button className="analyze-btn" onClick={handleGenerate} disabled={loading} style={{ maxWidth: '300px', margin: '0 auto' }}>
            {loading ? <Sparkles className="spin" size={20} /> : <Sparkles size={20} />}
            {loading ? "Generating Map..." : "Generate Quest Map"}
          </button>
        </div>
      ) : (
        <div className="results-container">
          <div className="stats-grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
            <div className="stat-card">
              <span className="stat-label">Duration</span>
              <div className="stat-value">
                {roadmap.total_days != null ? `${roadmap.total_days} Days` : `${roadmap.roadmap?.reduce((s, w) => s + w.days.length, 0) ?? '—'} Days`}
              </div>
            </div>
            <div className="stat-card">
              <span className="stat-label">Focus Skills</span>
              <div className="stat-value">{roadmap.total_skills ?? roadmap.roadmap?.length ?? '—'}</div>
            </div>
            <div className="stat-card">
              <span className="stat-label">Alignment</span>
              <div className="stat-value" style={{ color: roadmap.alignment_score > 70 ? 'var(--accent-secondary)' : 'var(--accent-orange)' }}>
                {roadmap.alignment_score != null ? `${roadmap.alignment_score}%` : '—'}
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.6rem 0.9rem', borderRadius: '8px', background: 'rgba(0,240,255,0.05)', border: '1px solid rgba(0,240,255,0.15)', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
            <BookOpen size={14} color="var(--accent-primary)" />
            Click any topic to get curated YouTube videos, docs, and practice resources
          </div>

          {roadmap.roadmap.map((week, i) => (
            <div key={i} className="result-card" style={{ borderLeft: '4px solid var(--accent-primary)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '1rem' }}>
                <h3>Week {week.week}: {week.focus_skill}</h3>
                <span className="skill-tag tech">XP: {week.importance * 100}</span>
              </div>
              <div className="quest-list">
                {week.days.map((day, j) => (
                  <div
                    key={j}
                    onClick={() => openDrawer(day, week.focus_skill)}
                    style={{
                      display: 'flex', gap: '1rem', padding: '10px 8px',
                      borderBottom: j < week.days.length - 1 ? '1px solid var(--border-color)' : 'none',
                      cursor: 'pointer', borderRadius: '8px', transition: 'background 0.15s',
                    }}
                    onMouseEnter={e => e.currentTarget.style.background = 'rgba(0,240,255,0.04)'}
                    onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                  >
                    <div style={{
                      minWidth: '24px', height: '24px', borderRadius: '50%',
                      border: '2px solid var(--text-muted)', display: 'flex',
                      alignItems: 'center', justifyContent: 'center', fontSize: '0.7rem',
                      color: 'var(--text-muted)', flexShrink: 0,
                    }}>
                      {day.day}
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{day.task}</div>
                      <p style={{ fontSize: '0.9rem', color: 'var(--text-muted)', marginTop: '4px' }}>{day.description}</p>
                    </div>
                    <BookOpen size={14} style={{ flexShrink: 0, color: 'var(--text-muted)', marginTop: '4px', opacity: 0.5 }} />
                  </div>
                ))}
              </div>
            </div>
          ))}

          <div className="result-card" style={{ border: '1px solid var(--accent-orange)', background: 'rgba(245, 158, 11, 0.05)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1rem' }}>
              <Trophy size={24} color="var(--accent-orange)" />
              <h3 style={{ margin: 0, color: 'var(--accent-orange)' }}>Boss Battle: Capstone Project</h3>
            </div>
            <div>
              <h4 style={{ fontSize: '1.1rem', marginBottom: '0.5rem' }}>{roadmap.capstone.task}</h4>
              <p style={{ color: 'var(--text-muted)' }}>{roadmap.capstone.description}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

const DailyQuest = ({ onComplete, selectedRole, allUserSkills, nextPrioritySkill }) => {
  const SKILL_OPTIONS = [
    'System Design', 'Python', 'JavaScript', 'React', 'Docker',
    'Kubernetes', 'SQL', 'Data Structures', 'Algorithms', 'AWS',
    'Machine Learning', 'TypeScript', 'Node.js', 'Git',
  ]

  const [selectedSkill, setSelectedSkill] = useState(nextPrioritySkill || '')
  const [challenge, setChallenge] = useState(null)
  const [submission, setSubmission] = useState('')
  const [loading, setLoading] = useState(false)
  const [fetchingChallenge, setFetchingChallenge] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

  const handleFetchChallenge = async () => {
    if (!selectedSkill) return
    setFetchingChallenge(true)
    setError(null)
    try {
      const data = await generateChallenge(selectedSkill)
      setChallenge(data)
    } catch (err) {
      setError(err.message || 'Failed to generate challenge.')
    } finally {
      setFetchingChallenge(false)
    }
  }

  const handleSubmit = async () => {
    if (!submission) return
    setLoading(true)
    setError(null)
    try {
      const payload = {
        user_id: 'user_1',
        submission_text: submission,
        skill: challenge?.skill || selectedSkill,
        task_context: challenge?.question || selectedSkill,
      }
      if (selectedRole)    payload.target_role  = selectedRole
      if (allUserSkills?.length) payload.user_skills = allUserSkills
      const data = await evaluateTask(payload)
      setResult(data)
      if (onComplete) onComplete()
    } catch (err) {
      setError(err.message || 'Submission failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const handleReset = () => {
    setChallenge(null)
    setResult(null)
    setSubmission('')
    setSelectedSkill('')
    setError(null)
  }

  return (
    <div className="scan-container">
      <div className="scan-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <div className="scan-title">
            <Swords size={32} color="var(--accent-primary)" />
            <h2>Eat the Frog</h2>
          </div>
          <p className="scan-subtitle">Pick a skill, get an AI challenge, earn XP.</p>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ color: 'var(--accent-orange)', fontWeight: 700 }}>+5–20 XP</div>
          <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>per quest</div>
        </div>
      </div>

      {result ? (
        <div className="results-container fade-in">
          <div className="result-card" style={{ textAlign: 'center', padding: '2rem' }}>
            <div style={{
              width: '64px', height: '64px', background: 'rgba(34, 197, 94, 0.1)',
              borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center',
              margin: '0 auto 1rem auto'
            }}>
              <Trophy size={32} color="var(--accent-secondary)" />
            </div>
            <h3 style={{ color: 'var(--accent-secondary)', marginBottom: '1rem' }}>Quest Complete!</h3>

            {result.next_priority_skill && (
              <div style={{
                background: 'rgba(0,240,255,0.06)', border: '1px solid rgba(0,240,255,0.25)',
                borderRadius: '12px', padding: '0.85rem 1.2rem', marginBottom: '1.25rem',
                display: 'flex', alignItems: 'center', gap: '0.75rem',
              }}>
                <span style={{ fontSize: '1.2rem' }}>🎯</span>
                <div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', letterSpacing: '0.05em', textTransform: 'uppercase' }}>Next Priority Skill</div>
                  <div style={{ fontWeight: 700, color: 'var(--accent-primary)', fontSize: '1rem' }}>{result.next_priority_skill}</div>
                </div>
              </div>
            )}

            <div className="stats-grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)', gap: '1rem' }}>
              <div className="stat-card">
                <span className="stat-label">Rating</span>
                <div className="stat-value" style={{ color: result.feedback?.rating >= 70 ? 'var(--accent-secondary)' : 'var(--accent-orange)' }}>
                  {result.feedback?.rating}/100
                </div>
              </div>
              <div className="stat-card">
                <span className="stat-label">XP Earned</span>
                <div className="stat-value" style={{ color: 'var(--accent-primary)' }}>+{result.xp}</div>
              </div>
              <div className="stat-card">
                <span className="stat-label">Streak</span>
                <div className="stat-value">{result.streak}🔥</div>
              </div>
            </div>
          </div>

          {result.feedback && (
            <>
              <div className="result-card">
                <h3 style={{ color: 'var(--accent-orange)' }}>Mistakes & Gaps</h3>
                <ul style={{ paddingLeft: '1.2rem', color: 'var(--text-muted)', lineHeight: '1.8' }}>
                  {result.feedback.mistakes.map((m, i) => <li key={i}>{m}</li>)}
                </ul>
              </div>
              <div className="result-card">
                <h3 style={{ color: 'var(--accent-secondary)' }}>Correct Approach</h3>
                <p style={{ color: 'var(--text-muted)', lineHeight: '1.7' }}>{result.feedback.correct_approach}</p>
              </div>
              <div className="result-card">
                <h3 style={{ color: 'var(--accent-primary)' }}>How to Improve</h3>
                <ul style={{ paddingLeft: '1.2rem', color: 'var(--text-muted)', lineHeight: '1.8' }}>
                  {result.feedback.improvements.map((imp, i) => <li key={i}>{imp}</li>)}
                </ul>
              </div>
            </>
          )}

          <button className="analyze-btn" onClick={handleReset} style={{ marginTop: '1rem' }}>
            <Swords size={20} />
            New Quest
          </button>
        </div>
      ) : !challenge ? (
        <div className="result-card fade-in" style={{ textAlign: 'center', padding: '3rem 2rem' }}>
          <div style={{
            width: '80px', height: '80px', background: 'var(--bg-tertiary)',
            borderRadius: '24px', display: 'flex', alignItems: 'center', justifyContent: 'center',
            margin: '0 auto 1.5rem auto', boxShadow: '0 0 20px rgba(0, 240, 255, 0.1)'
          }}>
            <Swords size={40} color="var(--accent-primary)" />
          </div>
        <h3 style={{ fontSize: '1.4rem', marginBottom: '0.5rem' }}>Choose Your Challenge</h3>
          <p style={{ color: 'var(--text-muted)', marginBottom: nextPrioritySkill ? '1rem' : '2rem' }}>
            Select a skill to receive an AI-generated challenge question
          </p>

          {nextPrioritySkill && (
            <div
              onClick={() => setSelectedSkill(nextPrioritySkill)}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: '0.6rem',
                padding: '0.6rem 1.1rem', borderRadius: '12px', cursor: 'pointer',
                marginBottom: '1.5rem',
                border: `2px solid ${selectedSkill === nextPrioritySkill ? 'var(--accent-primary)' : 'rgba(0,240,255,0.3)'}`,
                background: selectedSkill === nextPrioritySkill ? 'rgba(0,240,255,0.1)' : 'rgba(0,240,255,0.04)',
                transition: 'all 0.2s',
              }}
            >
              <span style={{ fontSize: '1rem' }}>🎯</span>
              <div style={{ textAlign: 'left' }}>
                <div style={{ fontSize: '0.65rem', color: 'var(--accent-primary)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em' }}>AI Recommended</div>
                <div style={{ fontWeight: 700, fontSize: '0.95rem', color: 'var(--text-primary)' }}>{nextPrioritySkill}</div>
              </div>
              {selectedSkill === nextPrioritySkill && <span style={{ color: 'var(--accent-primary)', fontWeight: 700, marginLeft: '0.4rem' }}>✓</span>}
            </div>
          )}
          <div className="skills-cloud" style={{ justifyContent: 'center', marginBottom: '2rem' }}>
            {nextPrioritySkill && (
              <div style={{ width: '100%', fontSize: '0.72rem', color: 'var(--text-muted)', textAlign: 'center', marginBottom: '0.5rem', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                Or choose another skill:
              </div>
            )}
            {SKILL_OPTIONS.map(skill => (
              <span
                key={skill}
                className="skill-tag tech"
                onClick={() => setSelectedSkill(skill)}
                style={{
                  cursor: 'pointer',
                  border: selectedSkill === skill ? '1px solid var(--accent-primary)' : '1px solid transparent',
                  background: selectedSkill === skill ? 'rgba(0,240,255,0.1)' : undefined,
                  color: selectedSkill === skill ? 'var(--accent-primary)' : undefined,
                  transition: 'all 0.2s ease',
                }}
              >
                {skill}
              </span>
            ))}
          </div>

          {error && <p style={{ color: 'var(--accent-orange)', marginBottom: '1rem', fontSize: '0.9rem' }}>⚠ {error}</p>}

          <button
            className="analyze-btn"
            onClick={handleFetchChallenge}
            disabled={!selectedSkill || fetchingChallenge}
            style={{ maxWidth: '300px', margin: '0 auto', opacity: !selectedSkill ? 0.5 : 1 }}
          >
            {fetchingChallenge ? <Sparkles className="spin" size={20} /> : <Zap size={20} />}
            {fetchingChallenge ? 'Generating Challenge...' : 'Get Challenge'}
          </button>
        </div>
      ) : (
        <div className="result-card fade-in">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1.5rem' }}>
            <span className="skill-tag tech" style={{ border: '1px solid var(--accent-primary)', color: 'var(--accent-primary)' }}>
              {challenge.skill}
            </span>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>AI-generated challenge</span>
          </div>
          <h3 style={{ fontSize: '1.05rem', lineHeight: '1.7', marginBottom: '1.5rem', color: 'var(--text-primary)' }}>
            {challenge.question}
          </h3>

          <textarea
            className="custom-input"
            style={{ height: '200px', padding: '1rem', resize: 'none', marginBottom: '1.5rem' }}
            placeholder="Write your answer here (be technical and specific)..."
            value={submission}
            onChange={(e) => setSubmission(e.target.value)}
          />

          {error && <p style={{ color: 'var(--accent-orange)', marginBottom: '1rem', fontSize: '0.9rem' }}>⚠ {error}</p>}

          <div style={{ display: 'flex', gap: '1rem' }}>
            <button
              className="analyze-btn"
              onClick={handleSubmit}
              disabled={loading || submission.length < 20}
              style={{ flex: 1 }}
            >
              {loading ? <Sparkles className="spin" size={20} /> : <Zap size={20} />}
              {loading ? 'Submitting...' : 'Submit Answer'}
            </button>
            <button
              onClick={() => setChallenge(null)}
              style={{
                padding: '0 1.5rem', borderRadius: '12px', border: '1px solid var(--border-color)',
                background: 'transparent', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '0.85rem'
              }}
            >
              Change Skill
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

const Gauge = ({ value, displayValue, label, color, size = 180 }) => {
  const radius = size * 0.45
  const stroke = size * 0.07
  const normalizedRadius = radius - stroke
  const circumference = normalizedRadius * 2 * Math.PI
  const strokeDashoffset = circumference - (value / 100) * circumference

  return (
    <div className="gauge-outer" style={{ width: size, textAlign: 'center' }}>
      <div className="gauge-container" style={{ width: size, height: size, position: 'relative', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <svg height={size} width={size} style={{ transform: 'rotate(-90deg)', position: 'absolute' }}>
          <circle
            stroke="var(--bg-tertiary)"
            fill="transparent"
            strokeWidth={stroke}
            r={normalizedRadius}
            cx={size / 2}
            cy={size / 2}
          />
          <circle
            stroke={color}
            fill="transparent"
            strokeWidth={stroke}
            strokeDasharray={circumference + ' ' + circumference}
            style={{ strokeDashoffset, transition: 'stroke-dashoffset 0.5s ease' }}
            strokeLinecap="round"
            r={normalizedRadius}
            cx={size / 2}
            cy={size / 2}
          />
        </svg>
        <div className="gauge-value" style={{ fontSize: `${size * 0.16}px`, fontWeight: 800, color: 'var(--text-primary)' }}>{displayValue || value}</div>
      </div>
      <div className="gauge-label" style={{ fontSize: '0.65rem', color: 'var(--text-muted)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', marginTop: '12px' }}>{label}</div>
    </div>
  )
}

const PlayerStats = ({ metrics, selectedRole, scanResult, masteryData }) => {
  if (!metrics) return <div className="loading-state"><Sparkles className="spin" /></div>

  const TIERS = [500, 1000, 2500, 5000]
  const xp = metrics.xp
  const nextTier = TIERS.find(t => xp < t) || TIERS[TIERS.length - 1]
  const prevTier = TIERS[TIERS.indexOf(nextTier) - 1] || 0
  const xpProgress = Math.min(((xp - prevTier) / (nextTier - prevTier)) * 100, 100)

  // Build skill proficiency from actual scanned skills if available, else fallback
  const scannedSkills = scanResult?.technical_skills || []
  const skillProfData = scannedSkills.length > 0
    ? scannedSkills.slice(0, 8).map((skill, i) => ({
        name: skill,
        value: Math.max(30, Math.round(80 - i * 7 + Math.random() * 10))
      }))
    : Object.entries(metrics.skill_distribution).map(([name, value]) => ({ name, value }))

  return (
    <div className="scan-container">
      <div className="scan-header">
        <div className="scan-title">
          <BarChart2 size={32} color="var(--accent-primary)" />
          <h2>Player Stats</h2>
        </div>
        <p className="scan-subtitle">Track your progress and climb the ranks.</p>
      </div>

      <div className="result-card career-warrior-card">
        <div className="warrior-badge">
          <Award size={48} color="var(--text-muted)" />
          <div className="warrior-rank-num">{metrics.level}</div>
        </div>
        <div style={{ flex: 1 }}>
          <h3 className="warrior-name">Career Warrior</h3>
          <p className="warrior-track">{metrics.rank || 'Unranked'} · {selectedRole || 'Developer'} Track</p>

          <div className="level-info" style={{ marginTop: '1.5rem' }}>
            <div className="level-text">
              <span>LVL {metrics.level} <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>→ {nextTier} XP</span></span>
              <span style={{ color: 'var(--text-muted)' }}>{xp}/{nextTier}</span>
            </div>
            <div className="progress-bar" style={{ height: '8px', background: 'var(--bg-primary)' }}>
              <div
                className="progress-fill"
                style={{
                  width: `${xpProgress}%`,
                  background: 'linear-gradient(90deg, var(--accent-secondary) 0%, var(--accent-primary) 100%)',
                  boxShadow: '0 0 10px rgba(0, 240, 255, 0.3)'
                }}
              ></div>
            </div>
          </div>

          <div className="warrior-stats-row">
            <span><Swords size={14} /> {metrics.total_completed_tasks} quests</span>
            <span><Flame size={14} /> {metrics.streak} streak</span>
            <span><Zap size={14} /> {metrics.execution_score.toFixed(0)} exec</span>
          </div>
        </div>
      </div>

      {/* ── Learned Skills ── */}
      {metrics.learned_skills?.length > 0 && (
        <div className="result-card" style={{ marginBottom: '1.5rem' }}>
          <h3 style={{ marginBottom: '0.9rem' }}>
            Learned Skills
            <span style={{ fontSize: '0.72rem', color: 'var(--accent-secondary)', fontWeight: 400, marginLeft: '0.6rem' }}>practised via Daily Quest</span>
          </h3>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
            {metrics.learned_skills.map(skill => (
              <span key={skill} style={{
                padding: '0.25rem 0.75rem', borderRadius: '999px', fontSize: '0.82rem', fontWeight: 600,
                background: 'rgba(0,240,255,0.08)', border: '1px solid rgba(0,240,255,0.25)',
                color: 'var(--accent-primary)',
              }}>
                {skill}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* ── Mastery Tracker (from Agentic Intelligence Loop) ── */}
      {masteryData?.mastery_levels?.length > 0 && (
        <div className="result-card" style={{ marginBottom: '1.5rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
            <h3 style={{ margin: 0 }}>
              Skill Mastery Levels
              <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontWeight: 400, marginLeft: '0.6rem' }}>computed by Mastery Tracker</span>
            </h3>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{masteryData.mastery_levels.length} skills</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.7rem' }}>
            {masteryData.mastery_levels.map(item => (
              <div key={item.skill} style={{ display: 'flex', alignItems: 'center', gap: '0.9rem' }}>
                <span style={{
                  minWidth: '110px', maxWidth: '130px', fontSize: '0.85rem', fontWeight: 600,
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  color: 'var(--text-primary)',
                }}>{item.skill}</span>
                <div style={{ flex: 1, height: '7px', background: 'var(--bg-tertiary)', borderRadius: '999px', overflow: 'hidden' }}>
                  <div style={{
                    height: '100%',
                    width: `${(item.level / 4) * 100}%`,
                    background: MASTERY_COLORS[item.level] || 'var(--accent-primary)',
                    borderRadius: '999px',
                    transition: 'width 0.6s ease',
                  }} />
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', minWidth: '110px', justifyContent: 'flex-end' }}>
                  <span style={{
                    fontSize: '0.72rem', fontWeight: 700,
                    color: MASTERY_COLORS[item.level] || 'var(--accent-primary)',
                  }}>{item.level_name}</span>
                  {item.skill_xp > 0 && (
                    <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)', background: 'var(--bg-tertiary)', padding: '0.1rem 0.4rem', borderRadius: '999px' }}>
                      {item.skill_xp} XP
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="charts-container" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem', marginBottom: '2rem' }}>
        <div className="result-card" style={{ height: '360px' }}>
          <h3>Knowledge Map</h3>
          <ResponsiveContainer width="100%" height="85%">
            <PieChart>
              <Pie
                data={metrics.knowledge_map}
                cx="50%"
                cy="50%"
                innerRadius={60}
                outerRadius={80}
                paddingAngle={5}
                dataKey="value"
              >
                {metrics.knowledge_map.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={entry.color} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{ backgroundColor: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', borderRadius: '8px' }}
              />
              <Legend verticalAlign="bottom" height={36} />
            </PieChart>
          </ResponsiveContainer>
        </div>

        <div className="result-card" style={{ height: '360px' }}>
          <h3>Skill Proficiency {scannedSkills.length > 0 && <span style={{ fontSize: '0.7rem', color: 'var(--accent-secondary)', fontWeight: 400, marginLeft: '0.5rem' }}>from profile scan</span>}</h3>
          <ResponsiveContainer width="100%" height="85%">
            <BarChart data={skillProfData} layout="vertical" margin={{ left: 10, right: 20 }}>
              <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="var(--border-color)" />
              <XAxis type="number" domain={[0, 100]} hide />
              <YAxis dataKey="name" type="category" stroke="var(--text-muted)" fontSize={11} tickLine={false} axisLine={false} width={90} />
              <Tooltip
                cursor={{ fill: 'rgba(255,255,255,0.05)' }}
                contentStyle={{ backgroundColor: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', borderRadius: '8px' }}
              />
              <Bar dataKey="value" radius={[0, 4, 4, 0]} barSize={14}>
                {skillProfData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={index % 2 === 0 ? 'var(--accent-primary)' : 'var(--accent-secondary)'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="result-card" style={{ height: '360px' }}>
          <h3>Skill Distribution</h3>
          <ResponsiveContainer width="100%" height="85%">
            <RadarChart cx="50%" cy="50%" outerRadius="70%" data={Object.entries(metrics.skill_distribution).map(([name, value]) => ({ subject: name, A: value, fullMark: 100 }))}>
              <PolarGrid stroke="var(--border-color)" />
              <PolarAngleAxis dataKey="subject" tick={{ fill: 'var(--text-muted)', fontSize: 12 }} />
              <PolarRadiusAxis angle={30} domain={[0, 100]} tick={false} axisLine={false} />
              <Radar
                name="Skills"
                dataKey="A"
                stroke="var(--accent-primary)"
                fill="var(--accent-primary)"
                fillOpacity={0.3}
              />
            </RadarChart>
          </ResponsiveContainer>
        </div>

        <div className="result-card" style={{ height: '360px' }}>
          <h3>Activity Curve</h3>
          <ResponsiveContainer width="100%" height="85%">
            <AreaChart
              data={metrics.activity_log}
              margin={{ top: 10, right: 10, left: 0, bottom: 0 }}
            >
              <defs>
                <linearGradient id="colorXp" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="var(--accent-secondary)" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="var(--accent-secondary)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="day" stroke="var(--text-muted)" fontSize={12} tickLine={false} axisLine={false} />
              <YAxis hide />
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border-color)" />
              <Tooltip
                contentStyle={{ backgroundColor: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', borderRadius: '8px' }}
                itemStyle={{ color: 'var(--accent-secondary)' }}
              />
              <Area type="monotone" dataKey="xp" stroke="var(--accent-secondary)" fillOpacity={1} fill="url(#colorXp)" strokeWidth={3} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="gauges-wrapper">
        <Gauge value={(metrics.total_completed_tasks / (metrics.total_assigned_tasks || 1) * 100).toFixed(0)} label="Quest Completion" color="var(--accent-primary)" size={180} />
        <Gauge value={metrics.execution_score.toFixed(0)} label="Execution Score" color="#8B5CF6" size={180} />
        <Gauge
          value={xpProgress}
          displayValue={500 - (metrics.xp % 500)}
          label="XP To Next LVL"
          color="#F59E0B"
          size={180}
        />
      </div>
    </div>
  )
}

export default App
