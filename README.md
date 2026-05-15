# AI Interviewer Platform

A professional, high-performance AI-driven interview platform featuring technical assessments, behavioral analysis, and a real-time proctoring engine.

## 🏗️ Architecture

- **Frontend**: Next.js 16 (App Router) with TailwindCSS.
- **Backend**: Flask (Python 3.10+) utilizing Torch, MediaPipe, and DeepFace for advanced analysis.
- **Database**: Dual-mode support for SQLite (Development) and PostgreSQL (Production).

## 🛠️ Local Development Setup

1. **Configure Environment Variables**:
   - Copy `backend/.env.example` to `backend/.env` and fill in credentials.
   - Copy `frontend/.env.example` to `frontend/.env` and set `NEXT_PUBLIC_API_URL` (for local use, typically `http://127.0.0.1:5000`).

### Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate
pip install -r requirements.txt
python api.py
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

## 📁 Project Structure

- `/frontend`: Next.js web application.
- `/backend`: Python API and processing engines.
- `/database`: Migration scripts and local database storage.
- `/scripts/maintenance`: Utility scripts for database fixing and management.
- `/logs`: Centralized log storage.

## 🔐 Security & Proctoring
The platform includes an advanced proctoring engine that monitors:
- Identity verification (Face Match).
- Eye contact tracking.
- Object detection (Mobile/Multiple people).
- Session behavior analysis.

---
© 2026 AI Interviewer Agent Team. All rights reserved.
