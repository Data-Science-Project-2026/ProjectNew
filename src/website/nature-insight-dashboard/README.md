# Nature Insight Dashboard

Nature Insight Dashboard is a web-based data visualization platform for exploring biodiversity observations, activity patterns, and human emotion responses across regions. The application combines a Vue 3 frontend with a FastAPI backend and a SQLite database for interactive map and chart analysis.

## Project Overview

This dashboard supports:

- species filtering by kingdom, category, and genus
- province-level geographic distribution analysis
- observation trend analysis over time
- activity pattern exploration
- emotional response trends and summaries
- co-occurrence network visualization for species relationships

## Technology Stack

- Frontend: Vue 3 + Vite
- Backend: FastAPI + SQLAlchemy
- Database: SQLite
- Visualization: ECharts
- Build tooling: npm + Vite

## Folder Structure

```text
nature-insight-dashboard/
├── backend/
│   ├── dashboard.db
│   ├── database.py
│   ├── main.py
│   ├── requirements.txt
│   ├── routers/
│   └── .venv/
├── src/
│   ├── App.vue
│   ├── components/
│   ├── router/
│   ├── stores/
│   ├── views/
│   └── assets/
├── public/
├── dist/
├── package.json
├── package-lock.json
├── vite.config.js
├── index.html
├── setup-backend.bat
├── start-all.bat
├── README.md
└── .gitignore
```

## Requirements

Before running the project, install:

- Python 3.10 or newer
- Node.js 18+ / npm
- Chrome, Edge, or Firefox

## Environment Setup

### 1. Backend setup

From the project root:

```bash
python -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install --upgrade pip
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
```

On Windows, you can instead run:

```bat
setup-backend.bat
```

### 2. Frontend setup

```bash
npm install
```

## Run the Application

### Start backend

```bash
cd backend
.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

### Start frontend

Open a second terminal in the project root:

```bash
npm run dev
```

Then open the browser:

- Frontend: http://localhost:5173
- API docs: http://127.0.0.1:8000/docs

### One-click Windows launch

Double-click:

```bat
start-all.bat
```

This script starts both the frontend and backend in separate windows and opens the app.

## Production Build

To build the frontend for deployment:

```bash
npm run build
```

This creates the production files in the `dist/` directory.

## Deployment Notes

For server deployment, the following should be included:

- source code for the frontend and backend
- database file: `backend/dashboard.db`
- dependency files: `package.json` and `backend/requirements.txt`
- startup instructions for Node and Python

Example backend deployment command:

```bash
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

## Main API Endpoints

- `/api/species/filter-options`
- `/api/species/years`
- `/api/species/trend`
- `/api/species/map`
- `/api/activity/filter-options`
- `/api/activity/trend`
- `/api/activity/map`
- `/api/emotion/top15`
- `/api/emotion/trend`
- `/api/emotion/map`

## Database

The project uses SQLite and stores the preprocessed observation statistics in:

```text
backend/dashboard.db
```

Key tables include:

- species_map_stats
- monthly_genus_stats
- activity_map_stats
- activity_trend_stats
- human_response_map_stats
- response_trend_stats
- top15_activity
- top15_emotion
- cooccur_edges

## Troubleshooting

### Frontend loads but charts are empty

Ensure the backend is running correctly on port 8000 and that the database file exists.

### Static file startup issue

If the backend reports a missing static directory, rebuild the frontend:

```bash
npm run build
```

Then restart the backend.

### Dependency issues

Reinstall dependencies:

```bash
npm install
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
```

## License

This project is intended for academic and research use. Please confirm dataset and library licensing before public distribution or commercial use.
