# 🚀 CareerCoach: Your AI-Powered Career Co-Pilot

**CareerCoach** is a high-fidelity, data-driven dashboard designed to gamify and accelerate your professional growth. It combines AI-powered skill analysis, real-time market data, and a tiered community system to transform your career journey into an epic quest.

---

## ✨ Key Features

### 🔍 1. AI Profile Scanning
Connect your professional identity (Resume/GitHub) to extract a deep-learning backed representation of your technical and soft skill proficiency. Uses **Ollama (LLM)** for intelligent skill mapping.

### 📊 2. Role-Gap Analysis
Compare your current skill set against real-time market demands. Our engine identifies high-priority "gaps" and suggests specific areas for improvement to make you the ideal candidate for your dream role.

### 🗺️ 3. Dynamic Roadmap & Quest Map
Don't just plan—execute. CareerOS generates a personalized roadmap with actionable "Quests." Visualize your path through the interactive Quest Map.

### 🐸 4. "Eat the Frog" Daily Quests
Tackle your most challenging task first with the **Daily Quest** system. Submit your work and receive **AI-powered brutal grading** and feedback to ensure you're actually leveling up.

### 📈 5. Player Stats & Visualizations
Your growth, visualized.
- **Knowledge Map**: Domain distribution (Backend, Frontend, AI, etc.).
- **Skill Proficiency**: Bar charts of your top competencies.
- **Skill Distribution**: Radar charts showing your professional balance.
- **Activity Curve**: Track your XP gains over time.

### 🏰 6. Tiered Discord Communities
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
