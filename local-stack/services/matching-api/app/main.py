from __future__ import annotations

import os
import secrets
import time
from typing import List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

app = FastAPI(title="Keoni Matching API", version="0.1.0")


class JobPayload(BaseModel):
    id: int
    title: str
    description: str = ""
    keywords: Optional[List[str]] = Field(default=None, description="Liste de mots-clés normalisés")
    location: Optional[str] = None
    meta: Optional[dict] = None


class CvPayload(BaseModel):
    id: int = Field(..., description="Identifiant interne du CV")
    candidate_email: Optional[str] = None
    application_title: Optional[str] = None
    text_content: Optional[str] = None
    metadata: Optional[dict] = None


class ScoreRequest(BaseModel):
    job: JobPayload
    cvs: List[CvPayload]


class ScoreItem(BaseModel):
    cv_id: int
    score: float
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    extra: dict = Field(default_factory=dict)


class ScoreResponse(BaseModel):
    job_id: int
    count: int
    duration_ms: int
    results: List[ScoreItem]


def require_api_key(x_api_key: str = Header(default="")) -> None:
    expected = os.getenv("MATCHING_API_KEY", "")
    if not expected or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


@app.get("/health")
def healthcheck() -> dict:
    return {
        "status": "ok",
        "model_cache": os.getenv("MODEL_CACHE", "/models"),
        "data_dir": os.getenv("DATA_DIR", "/data/cv_raw"),
        "time": time.time(),
    }


@app.post("/score", response_model=ScoreResponse)
def score(payload: ScoreRequest, _: None = Depends(require_api_key)) -> ScoreResponse:
    started = time.perf_counter()
    results: List[ScoreItem] = []

    for cv in payload.cvs:
        base_score = 0.0
        strengths: List[str] = []
        keywords: List[str] = []

        cv_text = (cv.text_content or "").lower()
        job_keywords = payload.job.keywords or []

        for kw in job_keywords:
            normalized = kw.lower()
            if normalized in cv_text:
                base_score += 5
                keywords.append(normalized)

        if payload.job.location and payload.job.location.lower() in (cv.metadata or {}).get("location", "").lower():
            base_score += 10
            strengths.append("Localisation correspondante")

        if cv.application_title and payload.job.title:
            shared_words = set(cv.application_title.lower().split()).intersection(payload.job.title.lower().split())
            if shared_words:
                base_score += 15
                strengths.append(f"Titre proche ({', '.join(sorted(shared_words))})")

        score_value = min(100.0, base_score)
        results.append(
            ScoreItem(
                cv_id=cv.id,
                score=round(score_value, 2),
                strengths=strengths,
                weaknesses=[],
                keywords=keywords,
                extra={"heuristic": True},
            )
        )

    duration_ms = int((time.perf_counter() - started) * 1000)

    return ScoreResponse(job_id=payload.job.id, count=len(results), duration_ms=duration_ms, results=results)
