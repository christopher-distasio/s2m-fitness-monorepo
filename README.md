# Speak2Me Fitness

A voice-first, accessibility-focused food logging app built to demonstrate AI integration and universal design principles.

## Stack

**Backend**: FastAPI, Python 3.11, Poetry  
**Database**: MongoDB Atlas (Beanie ODM)  
**Frontend**: Next.js 14, TypeScript, Tailwind CSS  
**Auth**: Supabase Auth (JWT, email/password)  
**AI**: OpenAI Whisper (STT), GPT-4o-mini (nutrition parsing + intent classification)  
**Deployment**: Render (backend), Vercel (frontend)

## Features

- **Voice-First Logging**: Record meals with 8-second auto-stop; Whisper transcribes to text
- **Structured Nutrition Parsing**: GPT-4o-mini extracts food items, quantities, and macros; returns structured JSON
- **Intent Classification**: Distinguish logging, summary, and goal-update intents from voice input
- **Daily Summaries**: Aggregate calories and macros; compare to personalized goal
- **Accessibility Throughout**: WCAG-compliant, keyboard navigable, screen-reader tested
- **Session Persistence**: JWT-based auth with Supabase; user data isolated in MongoDB

## Getting Started

### Prerequisites
- Python 3.11+, Node.js 18+
- Poetry (Python), npm or yarn (Node)
- MongoDB Atlas account (or local instance)
- Supabase project
- OpenAI API key

### Backend Setup

```bash
cd backend
poetry install
poetry run uvicorn app.main:app --reload
```

Environment variables (`.env`):
```
MONGODB_URL=...
SUPABASE_URL=...
SUPABASE_SERVICE_KEY=...
OPENAI_API_KEY=...
```

### Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Environment variables (`.env.local`):
```
NEXT_PUBLIC_SUPABASE_URL=...
NEXT_PUBLIC_SUPABASE_ANON_KEY=...
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## API Endpoints

- `POST /auth/register` – User signup
- `POST /auth/login` – User login
- `POST /logs` – Create food log from voice transcript
- `GET /logs?date=YYYY-MM-DD` – Fetch logs for date
- `GET /summary?date=YYYY-MM-DD` – Daily totals + goal comparison
- `GET /profile` – Fetch user calorie goal
- `PATCH /profile` – Update calorie goal

## Roadmap

**Stage 3**: Deploy to Render + Vercel _(in progress)_  
**Stage 4**: PWA implementation  
**Stage 5**: Voice correction flows, embeddings-based meal discovery, model evaluation

## Design Principles

- **Accessibility as Universal Design**: Voice-first serves multiple populations (hands-busy, vision-impaired, etc.) — it's a product insight, not just compliance
- **Feature Dependency Awareness**: Deferring features that need user context (summaries, weekly trends) until auth is solid
- **Shipping Credibility**: Building portfolio pieces that ship > accumulating credentials

## License

MIT