from __future__ import annotations

import logging
import os
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Iterable, List, Optional, Sequence, Tuple, Union

import faiss
import numpy as np
import pytesseract
from fastapi import Depends, FastAPI, Header, HTTPException, status
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field
from sentence_transformers import SentenceTransformer
from tika import parser

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(title="Keoni Matching API", version="0.2.0")

WORD_PATTERN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9']+")
DEFAULT_STOPWORDS = {
    "and",
    "the",
    "for",
    "les",
    "des",
    "une",
    "avec",
    "sur",
    "par",
    "un",
    "une",
    "aux",
    "von",
    "und",
    "pour",
    "entre",
    "dans",
    "from",
    "avec",
    "chez",
    "nos",
    "vos",
    "mon",
    "ton",
    "son",
    "his",
    "her",
    "our",
    "your",
    "their",
    "developpeur",
    "développeur",
    "developer",
    "dev",
    "full",
    "stack",
    "fullstack",
    "senior",
    "junior",
    "consultant",
    "chef",
    "projet",
    "project",
    "manager",
    "ingenieur",
    "ingénieur",
    "analyste",
    "architecte",
    "technicien",
    "administrateur",
    "responsable",
}


@dataclass(slots=True)
class Settings:
    sentence_model: str = os.getenv("SENTENCE_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    top_k: int = int(os.getenv("MATCHING_TOP_K", "200"))
    min_similarity: float = float(os.getenv("MATCHING_MIN_SIMILARITY", "0.2"))
    keyword_weight: float = float(os.getenv("MATCHING_KEYWORD_WEIGHT", "12"))
    keyword_boost_weight: float = float(os.getenv("MATCHING_KEYWORD_BOOST_WEIGHT", "8"))
    keyword_boost_threshold: int = int(os.getenv("MATCHING_KEYWORD_BOOST_THRESHOLD", "2"))
    title_weight: float = float(os.getenv("MATCHING_TITLE_WEIGHT", "10"))
    location_weight: float = float(os.getenv("MATCHING_LOCATION_WEIGHT", "5"))
    embed_batch_size: int = int(os.getenv("EMBED_BATCH_SIZE", "32"))
    data_dir: Path = Path(os.getenv("DATA_DIR", "/data/cv_raw"))
    require_signal: bool = os.getenv("MATCHING_REQUIRE_SIGNAL", "true").lower() == "true"
    min_keyword_hits: int = int(os.getenv("MATCHING_MIN_KEYWORD_HITS", "1"))
    exact_title_weight: float = float(os.getenv("MATCHING_EXACT_TITLE_WEIGHT", "25"))


settings = Settings()
_model: Optional[SentenceTransformer] = None
_model_lock = Lock()


class JobPayload(BaseModel):
    id: int
    title: str
    description: str = ""
    content: str = ""
    excerpt: str = ""
    keywords: Optional[Union[str, List[str]]] = Field(default=None, description="Liste ou chaîne de mots-clés")
    location: Optional[str] = None
    meta: Optional[dict] = None


class CvPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int = Field(..., description="Identifiant interne du CV")
    candidate_email: Optional[str] = None
    application_title: Optional[str] = None
    title: Optional[str] = None
    resume: Optional[str] = None
    text_content: Optional[str] = None
    skills: Optional[str] = None
    keywords: Optional[Union[str, List[str]]] = None
    metadata: Optional[dict] = None
    file_path: Optional[str] = None
    location: Optional[str] = None


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


@dataclass(slots=True)
class PreparedJob:
    text: str
    title: str
    tokens: set[str]
    keywords: List[str]
    keyword_set: set[str]
    location: str
    title_tokens: set[str]


@dataclass(slots=True)
class PreparedCv:
    payload: CvPayload
    text: str
    title_tokens: set[str]
    keywords: List[str]
    keyword_set: set[str]
    location: str


def require_api_key(x_api_key: str = Header(default="")) -> None:
    expected = os.getenv("MATCHING_API_KEY", "")
    if not expected or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                logging.info("Loading sentence-transformer model %s", settings.sentence_model)
                _model = SentenceTransformer(settings.sentence_model)
    return _model


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_title(value: str) -> str:
    cleaned = normalize_whitespace(value.lower())
    cleaned = re.sub(r"[^a-z0-9à-öø-ÿ\s]", " ", cleaned)
    return normalize_whitespace(cleaned)


def title_tokens(value: str) -> set[str]:
    normalized = normalize_title(value)
    if not normalized:
        return set()
    return set(normalized.split())


def tokenize(text: str) -> set[str]:
    tokens: set[str] = set()
    for match in WORD_PATTERN.finditer(text.lower()):
        word = match.group()
        if len(word) <= 2 or word in DEFAULT_STOPWORDS:
            continue
        tokens.add(word)
    return tokens


def parse_keywords(raw: Optional[Union[str, Sequence[str]]]) -> List[str]:
    if not raw:
        return []

    if isinstance(raw, str):
        candidates: Iterable[str] = re.split(r"[,;/\n]+", raw)
    else:
        candidates = raw

    seen: set[str] = set()
    keywords: List[str] = []
    for candidate in candidates:
        cleaned = normalize_whitespace(str(candidate)).lower()
        if not cleaned or len(cleaned) <= 2:
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        keywords.append(cleaned)
    return keywords


def resolve_file_path(raw_path: str) -> Optional[Path]:
    candidate = Path(raw_path)
    if candidate.is_file():
        return candidate
    nested = settings.data_dir / raw_path
    if nested.is_file():
        return nested
    return None


def text_from_file(path: Path) -> str:
    try:
        parsed = parser.from_file(str(path))
        content = parsed.get("content") or ""
        if content.strip():
            return normalize_whitespace(content)
    except Exception as exc:  # noqa: BLE001
        logging.warning("Tika parsing failed for %s: %s", path, exc)

    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".tiff", ".bmp"}:
        try:
            with Image.open(path) as img:
                content = pytesseract.image_to_string(img, lang="fra+eng")
                if content.strip():
                    return normalize_whitespace(content)
        except Exception as exc:  # noqa: BLE001
            logging.warning("OCR parsing failed for %s: %s", path, exc)

    return ""


def assemble_cv_text(cv: CvPayload) -> str:
    parts: List[str] = []
    for value in [cv.text_content, cv.resume, cv.skills]:
        if value:
            parts.append(value)

    meta = cv.metadata or {}
    for key in ("summary", "experience", "notes", "resume"):
        value = meta.get(key)
        if isinstance(value, str):
            parts.append(value)

    combined = normalize_whitespace(" ".join(parts))
    if combined:
        return combined

    file_candidate = cv.file_path or meta.get("file_path")
    if file_candidate:
        resolved = resolve_file_path(file_candidate)
        if resolved:
            file_text = text_from_file(resolved)
            if file_text:
                return file_text

    return ""


def prepare_job(job: JobPayload) -> PreparedJob:
    meta = job.meta or {}
    keywords = (
        parse_keywords(job.keywords)
        + parse_keywords(meta.get("skills"))
        + parse_keywords(job.description)
        + parse_keywords(job.content)
        + parse_keywords(job.excerpt)
    )
    keywords = list(dict.fromkeys(keywords))
    text_parts = [job.title, job.description, job.content, job.excerpt, " ".join(keywords), meta.get("experience", "")]
    text = normalize_whitespace(" ".join(filter(None, text_parts)))
    location = (job.location or meta.get("location") or "").lower()
    tokens = tokenize(f"{job.title} {job.description}")
    return PreparedJob(
        text=text,
        title=job.title,
        tokens=tokens,
        keywords=keywords,
        keyword_set=set(keywords),
        location=location,
        title_tokens=title_tokens(job.title),
    )


def prepare_cv(cv: CvPayload) -> PreparedCv:
    meta = cv.metadata or {}
    text = assemble_cv_text(cv)
    title_tokens = tokenize(" ".join(filter(None, [cv.application_title, cv.title])))
    keywords = parse_keywords(cv.keywords) + parse_keywords(meta.get("keywords")) + parse_keywords(cv.skills)
    keywords = list(dict.fromkeys(keywords))
    location = (cv.location or meta.get("location") or "").lower()
    return PreparedCv(payload=cv, text=text, title_tokens=title_tokens, keywords=keywords, keyword_set=set(keywords), location=location)


def encode_texts(texts: Sequence[str]) -> np.ndarray:
    model = get_model()
    embeddings = model.encode(list(texts), batch_size=settings.embed_batch_size, convert_to_numpy=True, normalize_embeddings=True)
    if not isinstance(embeddings, np.ndarray):
        embeddings = np.asarray(embeddings)
    return embeddings.astype("float32")


def search_top_matches(job_embedding: np.ndarray, cv_embeddings: np.ndarray, limit: int) -> Tuple[np.ndarray, np.ndarray]:
    limit = max(1, min(limit, len(cv_embeddings)))
    index = faiss.IndexFlatIP(cv_embeddings.shape[1])
    index.add(cv_embeddings)
    scores, indices = index.search(np.expand_dims(job_embedding, axis=0), limit)
    return indices[0], scores[0]


def build_score(job: PreparedJob, cv: PreparedCv, similarity: float, rank: int) -> ScoreItem:
    strengths: List[str] = []
    weaknesses: List[str] = []

    keyword_hits = sorted(job.keyword_set.intersection(cv.keyword_set))
    if keyword_hits:
        strengths.append(f"Mots-clés ({', '.join(keyword_hits[:5])})")
    else:
        weaknesses.append("Aucun mot-clé commun identifié")

    title_overlap = job.title_tokens.intersection(cv.title_tokens)
    job_title_norm = normalize_title(job.title)
    cv_title_raw = cv.payload.application_title or cv.payload.title or ""
    cv_title_norm = normalize_title(cv_title_raw)
    exact_title_match = bool(job_title_norm and cv_title_norm and job_title_norm == cv_title_norm)
    strong_title_match = bool(job.title_tokens and job.title_tokens.issubset(title_tokens(cv_title_raw)))
    if exact_title_match:
        strengths.append("Titre identique")
    elif strong_title_match:
        strengths.append("Titre très proche")
    elif title_overlap:
        strengths.append(f"Titre proche ({', '.join(sorted(title_overlap)[:3])})")
    else:
        weaknesses.append("Titre éloigné du besoin")

    location_bonus = 0.0
    if job.location and cv.location:
        if job.location in cv.location or cv.location in job.location:
            strengths.append("Localisation compatible")
            location_bonus = settings.location_weight
        else:
            weaknesses.append("Localisation différente")

    base_score = max(0.0, similarity) * 70
    score = base_score + len(keyword_hits) * settings.keyword_weight
    if len(keyword_hits) >= settings.keyword_boost_threshold:
        score += settings.keyword_boost_weight
    if exact_title_match:
        score += settings.exact_title_weight
    elif strong_title_match:
        score += settings.title_weight + 5
    elif title_overlap:
        score += settings.title_weight
    score += location_bonus
    score = float(max(0.0, min(100.0, score)))

    extra = {
        "vector_similarity": round(float(similarity), 4),
        "keyword_hits": keyword_hits,
        "rank": rank + 1,
        "exact_title_match": exact_title_match,
        "strong_title_match": strong_title_match,
    }

    return ScoreItem(
        cv_id=cv.payload.id,
        score=round(score, 2),
        strengths=strengths,
        weaknesses=weaknesses,
        keywords=keyword_hits,
        extra=extra,
    )


def has_matching_signal(keyword_hits: Sequence[str], title_overlap: set[str]) -> bool:
    return bool(keyword_hits) or bool(title_overlap)


@app.get("/health")
def healthcheck() -> dict:
    return {
        "status": "ok",
        "model": settings.sentence_model,
        "model_cache": os.getenv("MODEL_CACHE", "/models"),
        "data_dir": str(settings.data_dir),
        "time": time.time(),
    }


@app.post("/score", response_model=ScoreResponse)
def score(payload: ScoreRequest, _: None = Depends(require_api_key)) -> ScoreResponse:
    if not payload.cvs:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Aucun CV fourni")

    started = time.perf_counter()

    job = prepare_job(payload.job)
    prepared_cvs = [prepare_cv(cv) for cv in payload.cvs]
    usable = [cv for cv in prepared_cvs if cv.text]

    if usable:
        job_title_norm = normalize_title(payload.job.title)
        exact_title = [
            cv for cv in usable
            if job_title_norm
            and normalize_title(cv.payload.application_title or cv.payload.title or "") == job_title_norm
        ]
        if exact_title:
            usable = exact_title
        else:
            strong_title = [
                cv for cv in usable
                if job.title_tokens
                and job.title_tokens.issubset(title_tokens(cv.payload.application_title or cv.payload.title or ""))
            ]
            if strong_title:
                usable = strong_title

    if not usable:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Aucun texte exploitable pour les CV")

    job_embedding = encode_texts([job.text])[0]
    cv_embeddings = encode_texts([cv.text for cv in usable])

    indices, similarities = search_top_matches(job_embedding, cv_embeddings, settings.top_k)

    scored_items: List[ScoreItem] = []
    exact_title_present = False
    strong_title_present = False
    for rank, (idx, sim) in enumerate(zip(indices, similarities)):
        if idx < 0:
            continue
        if sim < settings.min_similarity:
            continue
        cv = usable[idx]
        keyword_hits = job.keyword_set.intersection(cv.keyword_set)
        title_overlap = job.title_tokens.intersection(cv.title_tokens)
        job_title_norm = normalize_title(payload.job.title)
        cv_title_raw = cv.payload.application_title or cv.payload.title or ""
        cv_title_norm = normalize_title(cv_title_raw)
        if job_title_norm and cv_title_norm and job_title_norm == cv_title_norm:
            exact_title_present = True
        if job.title_tokens and job.title_tokens.issubset(title_tokens(cv_title_raw)):
            strong_title_present = True
        if job.keyword_set and len(keyword_hits) < settings.min_keyword_hits:
            continue
        if settings.require_signal and not has_matching_signal(keyword_hits, title_overlap):
            continue
        scored_items.append(build_score(job, cv, sim, rank))

    if exact_title_present:
        scored_items = [item for item in scored_items if item.extra.get("exact_title_match")]

    if not exact_title_present and strong_title_present:
        scored_items = [item for item in scored_items if item.extra.get("strong_title_match")]

    if not scored_items and len(indices) and not settings.require_signal:
        idx = int(indices[0])
        if idx >= 0:
            scored_items.append(build_score(job, usable[idx], float(similarities[0]), 0))

    duration_ms = int((time.perf_counter() - started) * 1000)

    return ScoreResponse(job_id=payload.job.id, count=len(scored_items), duration_ms=duration_ms, results=scored_items)
