"""FastAPI endpoints for the technical-debt analysis workflow."""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from .analysis import analyze_repository

app = FastAPI(title="Tech Debt Agent", version="0.1.0", description="Explainable, multi-stage repository debt analysis")


class AnalyzeRequest(BaseModel):
    repo_path: str = Field(..., description="Path to a local repository directory")


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "tech-debt-agent"}


@app.post("/api/analyze")
def analyze(request: AnalyzeRequest):
    try:
        return analyze_repository(request.repo_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# Serve the dashboard from the same origin as the API so browsers allow its
# requests without CORS configuration or opening the HTML as a local file.
app.mount("/", StaticFiles(directory=Path(__file__).resolve().parent.parent / "frontend", html=True), name="frontend")
