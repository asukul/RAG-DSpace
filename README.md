# ISU Research Search

AI-powered research search application for Iowa State University's DSpace repository.

## Features

- 🔍 **Semantic Search** - AI-powered document search using Google Gemini
- 👥 **People Search** - Find researchers by name, department, college, or topic
- 🗺️ **Topic Discovery** - Automatically discover research topics from documents
- 📊 **Admin Dashboard** - Manage faculty, documents, and system settings

## Tech Stack

- **Frontend**: React + Vite
- **Backend**: FastAPI (Python)
- **Database**: Firestore (GCP) / JSON files (local)
- **AI**: Google Gemini API
- **Deployment**: Google Cloud Run

## Local Development

```bash
# Start with Docker Compose
docker-compose up

# Frontend: http://localhost:3000
# Backend: http://localhost:8000
```

## Deployment

Push to main branch triggers automatic deployment via Cloud Build:

```bash
git add .
git commit -m "Your changes"
git push origin main
```

## License

MIT
