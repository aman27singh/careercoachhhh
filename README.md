# 🚀 CareerCoach: Agentic AI-Powered Career Co-Pilot

**CareerCoach** is an agentic AI system that autonomously analyzes your skills, tracks mastery, and recommends high-impact actions based on real market data. The agentic intelligence loop continuously updates your roadmap, mastery tracker, and questing system, ensuring you always receive the most relevant, personalized guidance.

---

## ✨ Key Features

### 🤖 Agentic Intelligence Hub
A fully autonomous intelligence engine that continuously analyzes your profile, market trends, and skill gaps. The agentic loop proactively recommends next actions, updates mastery, and surfaces new quests—no manual refresh needed.

### 🔍 AI Profile Scanning
Connect your professional identity (Resume/GitHub) to extract a deep-learning backed representation of your technical and soft skill proficiency. Uses **Ollama (LLM)** for intelligent skill mapping.

### 📊 Role-Gap Analysis
Compare your current skill set against real-time market demands. Our agentic engine identifies high-priority "gaps" and suggests specific areas for improvement to make you the ideal candidate for your dream role.

### 🗺️ Dynamic Roadmap & Agentic Quest Map
CareerOS generates a personalized roadmap with actionable "Agentic Quests." Visualize your path through the interactive Quest Map, updated continuously by the agentic loop.

### 🐸 Agentic Daily Quests
Tackle your most challenging task first with the **Agentic Daily Quest** system. Submit your work and receive **AI-powered grading** and feedback, ensuring continuous progress.

### 📈 Continuous Progress Engine (Mastery Tracker)
Your growth, visualized and tracked by the agentic mastery engine. Skill mastery levels are updated automatically, reflecting your real progress.

### 🏰 Tiered Discord Communities
Unlock access to specialized professional guilds as you gain XP.
- **Beginner Community** (500 XP)
- **Intermediate Community** (1000 XP)
- **Advanced Community** (2500 XP)
- **Expert Community** (5000 XP)

---

## 🛠️ Tech Stack

### Frontend
- **Framework**: React.js with Vite
- **Styling**: Vanilla CSS (High-fidelity "Glassmorphism" Design)
- **Visualization**: Recharts
- **Icons**: Lucide-React

### Backend
- **Framework**: FastAPI (Python)
- **AI Engine**: Ollama (Running localized LLMs)
- **Data Store**: JSON-based Persistence (for high performance and simplicity)
- **Logging**: Integrated backend logging

---

## 🚀 Getting Started

### Prerequisites
- Python 3.9+
- Node.js & npm
- [Ollama](https://ollama.ai/) (for AI features)

### 1. Backend Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Start the FastAPI server
uvicorn app.main:app --reload
```

### 2. Frontend Setup
```bash
cd frontend

# Install dependencies
npm install

# Start the dev server
npm run dev
```

### 3. AI Setup (Ollama)
Ensure Ollama is running locally:
```bash
ollama serve
# Ensure you have the required model (e.g., llama3 or similar)
ollama run llama3
```

---

## � AWS Deployment (Docker / ECS)

### Build & run locally

```bash
# Build the image
docker build -t careeros-backend .

# Run with AWS credentials and required env vars
docker run -p 8000:8000 \
  -e AWS_REGION=us-east-1 \
  -e AWS_ACCESS_KEY_ID=<key> \
  -e AWS_SECRET_ACCESS_KEY=<secret> \
  -e AWS_SESSION_TOKEN=<token> \          # if using temporary credentials
  -e OPENSEARCH_ENDPOINT=https://<id>.us-east-1.aoss.amazonaws.com \
  -e OPENSEARCH_INDEX=careercoach-docs \
  -e DYNAMODB_TABLE=careercoach-users \
  careeros-backend
```

Health-check: `curl http://localhost:8000/health`

### Push to Amazon ECR

```bash
# Authenticate
aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS \
    --password-stdin <account-id>.dkr.ecr.us-east-1.amazonaws.com

# Tag & push
docker tag careeros-backend \
  <account-id>.dkr.ecr.us-east-1.amazonaws.com/careeros-backend:latest

docker push \
  <account-id>.dkr.ecr.us-east-1.amazonaws.com/careeros-backend:latest
```

### ECS (Fargate) task — required environment variables

| Variable | Description | Example |
|---|---|---|
| `AWS_REGION` | AWS region | `us-east-1` |
| `OPENSEARCH_ENDPOINT` | Full HTTPS URL of the OpenSearch Serverless collection | `https://<id>.us-east-1.aoss.amazonaws.com` |
| `OPENSEARCH_INDEX` | Index name | `careercoach-docs` |
| `DYNAMODB_TABLE` | DynamoDB table for user state | `careercoach-users` |
| `PORT` | Container listen port (optional) | `8000` |

> **IAM permissions required for the task role:**
> `bedrock:InvokeModel`, `aoss:APIAccessAll` (or scoped collection policy), `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`

---

## �📂 Project Structure

```text
├── app/                  # FastAPI Backend
│   ├── data/             # JSON Data Store (User metrics, Market data)
│   ├── services/         # AI Engines (Profile, Roadmap, Eval)
│   └── models.py         # Data schemas
├── frontend/             # React/Vite Frontend
│   ├── src/              # App logic and components
│   └── App.css           # Custom Design System
└── scripts/              # Data processing utilities
```

---

## 👤 User Customization
User metrics are stored in `app/data/users/user_1.json`. You can manually adjust XP, Levels, and Skill weights here for testing and verification.

---

**Built with ❤️ for the next generation of top-tier developers.**
