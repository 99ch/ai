from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Iterable, List, Optional, Sequence, Tuple, Union

import tempfile
from urllib.parse import urlparse

import faiss
import numpy as np
import pytesseract
import requests
from fastapi import Depends, FastAPI, Header, HTTPException, status
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field
from sentence_transformers import SentenceTransformer
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from tika import parser

from app.db import get_engine, init_db
from app.models import CvEmbedding, JobEmbedding

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
}


@dataclass(slots=True)
class Settings:
    sentence_model: str = os.getenv("SENTENCE_MODEL", "intfloat/multilingual-e5-base")
    top_k: int = int(os.getenv("MATCHING_TOP_K", "200"))
    min_similarity: float = float(os.getenv("MATCHING_MIN_SIMILARITY", "0.2"))
    keyword_weight: float = float(os.getenv("MATCHING_KEYWORD_WEIGHT", "5"))
    title_weight: float = float(os.getenv("MATCHING_TITLE_WEIGHT", "10"))
    location_weight: float = float(os.getenv("MATCHING_LOCATION_WEIGHT", "5"))
    category_weight: float = float(os.getenv("MATCHING_CATEGORY_WEIGHT", "6"))
    jobtype_weight: float = float(os.getenv("MATCHING_JOBTYPE_WEIGHT", "8"))
    experience_weight: float = float(os.getenv("MATCHING_EXPERIENCE_WEIGHT", "8"))
    salary_weight: float = float(os.getenv("MATCHING_SALARY_WEIGHT", "6"))
    qualification_penalty: float = float(os.getenv("MATCHING_QUALIFICATION_PENALTY", "20"))
    hard_filter_jobtype: bool = os.getenv("MATCHING_HARD_FILTER_JOBTYPE", "1") == "1"
    hard_filter_qualification: bool = os.getenv("MATCHING_HARD_FILTER_QUALIFICATION", "1") == "1"
    embed_batch_size: int = int(os.getenv("EMBED_BATCH_SIZE", "32"))
    preload_model: bool = os.getenv("MATCHING_PRELOAD_MODEL", "1") == "1"
    data_dir: Path = Path(os.getenv("DATA_DIR", "/data/cv_raw"))
    file_fetch_timeout_seconds: int = int(os.getenv("MATCHING_FILE_FETCH_TIMEOUT", "15"))
    file_fetch_max_bytes: int = int(os.getenv("MATCHING_FILE_FETCH_MAX_BYTES", str(20 * 1024 * 1024)))


settings = Settings()
_model: Optional[SentenceTransformer] = None
_model_lock = Lock()
_pgvector_ready = False


@app.on_event("startup")
def init_persistence() -> None:
    global _pgvector_ready
    _pgvector_ready = init_db()
    if _pgvector_ready:
        logging.info("Embeddings persistants pgvector activés")


@app.on_event("startup")
def warmup_model() -> None:
    if not settings.preload_model:
        logging.info("Model warmup disabled (MATCHING_PRELOAD_MODEL=0)")
        return

    started = time.perf_counter()
    try:
        model = get_model()
        model.encode(["warmup"], batch_size=1, convert_to_numpy=True, normalize_embeddings=True)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logging.info("Model preloaded and warmed in %d ms", elapsed_ms)
    except Exception as exc:  # noqa: BLE001
        logging.warning("Model warmup failed: %s", exc)


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
    tokens: set[str]
    keywords: List[str]
    keyword_set: set[str]
    location: str
    category: str
    jobtype: str
    min_experience_years: Optional[float]
    salary_min: Optional[float]
    salary_max: Optional[float]


@dataclass(slots=True)
class PreparedCv:
    payload: CvPayload
    text: str
    text_tokens: set[str]
    title_tokens: set[str]
    keywords: List[str]
    keyword_set: set[str]
    location: str
    category: str
    jobtype: str
    experience_years: Optional[float]
    salary_expected_min: Optional[float]
    salary_expected_max: Optional[float]
    qualified: Optional[bool]


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


def normalized_text(value: Optional[object]) -> str:
    if value is None:
        return ""
    return normalize_whitespace(str(value)).lower()


def parse_float(value: Optional[object]) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip().replace(",", ".")
    if not text:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def parse_range(value: Optional[object]) -> Tuple[Optional[float], Optional[float]]:
    if value is None:
        return None, None
    text = str(value).strip().replace(",", ".")
    if not text:
        return None, None
    numbers = [float(m) for m in re.findall(r"\d+(?:\.\d+)?", text)]
    if not numbers:
        return None, None
    if len(numbers) == 1:
        return numbers[0], numbers[0]
    return min(numbers), max(numbers)


def parse_boolish(value: Optional[object]) -> Optional[bool]:
    if value is None:
        return None
    text = normalized_text(value)
    if not text:
        return None
    yes_values = {"yes", "oui", "true", "1", "qualifie", "qualifié", "ok"}
    no_values = {"no", "non", "false", "0", "ko"}
    if text in yes_values:
        return True
    if text in no_values:
        return False
    return None


def find_first(source: dict, keys: Sequence[str]) -> Optional[object]:
    for key in keys:
        if key in source and source.get(key) not in (None, ""):
            return source.get(key)
    return None


def overlap_text(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    a_tokens = set(tokenize(a))
    b_tokens = set(tokenize(b))
    return bool(a_tokens.intersection(b_tokens))


def resolve_file_path(raw_path: str) -> Optional[Path]:
    candidate = Path(raw_path)
    if candidate.is_file():
        return candidate
    nested = settings.data_dir / raw_path
    if nested.is_file():
        return nested
    return None


def fetch_remote_file(url: str) -> Optional[Path]:
    """Télécharge un CV distant (ex. URL publique WordPress) vers un fichier temporaire.

    Le fichier réel du candidat (uploadé via JS Job Manager) vit souvent sur un
    serveur WordPress distinct de matching-api ; on le récupère à la volée plutôt
    que de dépendre d'un volume partagé.
    """
    suffix = Path(urlparse(url).path).suffix or ".bin"

    try:
        with requests.get(url, timeout=settings.file_fetch_timeout_seconds, stream=True) as response:
            response.raise_for_status()

            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                written = 0
                for chunk in response.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > settings.file_fetch_max_bytes:
                        logging.warning("Remote CV file too large, aborting download: %s", url)
                        tmp.close()
                        Path(tmp.name).unlink(missing_ok=True)
                        return None
                    tmp.write(chunk)

                return Path(tmp.name)
    except Exception as exc:  # noqa: BLE001
        logging.warning("Failed to fetch remote CV file %s: %s", url, exc)
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
        is_remote = urlparse(file_candidate).scheme in ("http", "https")
        resolved = fetch_remote_file(file_candidate) if is_remote else resolve_file_path(file_candidate)

        if resolved:
            try:
                file_text = text_from_file(resolved)
                if file_text:
                    return file_text
            finally:
                if is_remote:
                    resolved.unlink(missing_ok=True)

    return ""


def prepare_job(job: JobPayload) -> PreparedJob:
    meta = job.meta or {}
    keywords = parse_keywords(job.keywords) + parse_keywords(meta.get("skills"))
    keywords = list(dict.fromkeys(keywords))
    text_parts = [job.title, job.description, job.content, job.excerpt, " ".join(keywords), meta.get("experience", "")]
    text = normalize_whitespace(" ".join(filter(None, text_parts)))
    location = (job.location or meta.get("location") or "").lower()
    tokens = tokenize(f"{job.title} {job.description}")
    category = normalized_text(find_first(meta, ["jobcategory_text", "category_text", "job_category", "category"]))
    jobtype = normalized_text(find_first(meta, ["jobtype_text", "job_type", "type", "jobtype"]))
    min_experience_years = parse_float(find_first(meta, ["experience", "min_experience", "required_experience"]))

    salary_min = parse_float(find_first(meta, ["salaryfrom", "salary_min", "salary_from"]))
    salary_max = parse_float(find_first(meta, ["salaryto", "salary_max", "salary_to", "tjm", "salary"]))

    return PreparedJob(
        text=text,
        tokens=tokens,
        keywords=keywords,
        keyword_set=set(keywords),
        location=location,
        category=category,
        jobtype=jobtype,
        min_experience_years=min_experience_years,
        salary_min=salary_min,
        salary_max=salary_max,
    )


def prepare_cv(cv: CvPayload) -> PreparedCv:
    meta = cv.metadata or {}
    raw = cv.model_dump()
    text = assemble_cv_text(cv)
    text_tokens = tokenize(text) if text else set()
    title_tokens = tokenize(" ".join(filter(None, [cv.application_title, cv.title])))
    keywords = parse_keywords(cv.keywords) + parse_keywords(meta.get("keywords")) + parse_keywords(cv.skills)
    keywords = list(dict.fromkeys(keywords))
    location = (cv.location or meta.get("location") or "").lower()

    category = normalized_text(
        find_first(raw, ["category_text", "category", "job_category"]) or find_first(meta, ["category_text", "category", "job_category"])
    )
    jobtype = normalized_text(
        find_first(raw, ["job_type", "type", "jobtype", "jobtype_text"]) or find_first(meta, ["job_type", "type", "jobtype", "jobtype_text"])
    )
    experience_years = parse_float(
        find_first(raw, ["total_experience", "experience", "experience_years"]) or find_first(meta, ["total_experience", "experience", "experience_years"])
    )
    salary_min, salary_max = parse_range(
        find_first(raw, ["salary_requested", "salary", "salary_range", "expected_salary", "tjm"]) or find_first(meta, ["salary_requested", "salary", "salary_range", "expected_salary", "tjm"])
    )
    qualified = parse_boolish(
        find_first(raw, ["qualified_for_job", "qualified", "qualifie", "qualifié"]) or find_first(meta, ["qualified_for_job", "qualified", "qualifie", "qualifié"])
    )

    return PreparedCv(
        payload=cv,
        text=text,
        text_tokens=text_tokens,
        title_tokens=title_tokens,
        keywords=keywords,
        keyword_set=set(keywords),
        location=location,
        category=category,
        jobtype=jobtype,
        experience_years=experience_years,
        salary_expected_min=salary_min,
        salary_expected_max=salary_max,
        qualified=qualified,
    )


def passes_hard_filters(job: PreparedJob, cv: PreparedCv) -> Tuple[bool, List[str]]:
    reasons: List[str] = []

    if settings.hard_filter_qualification and cv.qualified is False:
        reasons.append("Candidat non qualifié pour le poste")

    if settings.hard_filter_jobtype and job.jobtype and cv.jobtype and not overlap_text(job.jobtype, cv.jobtype):
        reasons.append("Type de contrat incompatible")

    if job.min_experience_years is not None and cv.experience_years is not None:
        if cv.experience_years + 0.5 < job.min_experience_years:
            reasons.append("Expérience insuffisante")

    return len(reasons) == 0, reasons


def compute_experience_adjustment(min_years: float, cv_years: float, weight: float) -> Tuple[float, float]:
    """Return (bonus, penalty) for experience with progressive scaling."""
    gap = cv_years - min_years
    denominator = max(1.0, min_years)

    if gap >= 0:
        # At threshold -> 50% of weight, then ramps to 100% when profile is clearly above requirement.
        ratio = min(1.0, 0.5 + (gap / denominator) * 0.5)
        return weight * ratio, 0.0

    # Below requirement -> progressive penalty up to full weight.
    deficit_ratio = min(1.0, abs(gap) / denominator)
    return 0.0, weight * (0.5 + 0.5 * deficit_ratio)


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


def content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def embedding_text(value: str, kind: str) -> str:
    """Préfixe query:/passage: attendu par les modèles E5 (intfloat/multilingual-e5-*)."""
    if "e5" not in settings.sentence_model.lower():
        return value
    prefix = "query: " if kind == "query" else "passage: "
    return f"{prefix}{value}"


def rank_with_faiss(job: PreparedJob, candidates: List[PreparedCv], top_k: int) -> List[Tuple[PreparedCv, float]]:
    job_embedding = encode_texts([embedding_text(job.text, "query")])[0]
    cv_embeddings = encode_texts([embedding_text(cv.text, "passage") for cv in candidates])
    indices, similarities = search_top_matches(job_embedding, cv_embeddings, top_k)
    return [(candidates[idx], float(sim)) for idx, sim in zip(indices, similarities) if idx >= 0]


def rank_with_pgvector(
    job: PreparedJob, job_id: int, candidates: List[PreparedCv], top_k: int
) -> Optional[List[Tuple[PreparedCv, float]]]:
    """Classe les candidats via pgvector, en ne ré-encodant que ce qui a changé.

    Retourne None si la base n'est pas disponible ou en cas d'erreur, pour
    déclencher le repli sur rank_with_faiss().
    """
    engine = get_engine()
    if engine is None:
        return None

    candidates_by_id = {cv.payload.id: cv for cv in candidates}
    cv_ids = list(candidates_by_id.keys())

    try:
        with engine.begin() as conn:
            job_text_hash = content_hash(job.text)
            existing_job = conn.execute(
                select(JobEmbedding.content_hash, JobEmbedding.embedding).where(JobEmbedding.job_id == job_id)
            ).first()

            if existing_job and existing_job.content_hash == job_text_hash:
                job_vector = np.asarray(existing_job.embedding, dtype="float32")
            else:
                job_vector = encode_texts([embedding_text(job.text, "query")])[0]
                job_stmt = pg_insert(JobEmbedding).values(
                    job_id=job_id, content_hash=job_text_hash, embedding=job_vector.tolist()
                )
                job_stmt = job_stmt.on_conflict_do_update(
                    index_elements=[JobEmbedding.job_id],
                    set_={
                        "content_hash": job_stmt.excluded.content_hash,
                        "embedding": job_stmt.excluded.embedding,
                        "updated_at": func.now(),
                    },
                )
                conn.execute(job_stmt)

            existing_rows = conn.execute(
                select(CvEmbedding.cv_id, CvEmbedding.content_hash).where(CvEmbedding.cv_id.in_(cv_ids))
            ).all()
            existing_hashes = {row.cv_id: row.content_hash for row in existing_rows}
            cv_hashes = {cv_id: content_hash(candidates_by_id[cv_id].text) for cv_id in cv_ids}
            stale_ids = [cv_id for cv_id in cv_ids if existing_hashes.get(cv_id) != cv_hashes[cv_id]]

            if stale_ids:
                vectors = encode_texts([embedding_text(candidates_by_id[cv_id].text, "passage") for cv_id in stale_ids])
                for i, cv_id in enumerate(stale_ids):
                    cv_stmt = pg_insert(CvEmbedding).values(
                        cv_id=cv_id, content_hash=cv_hashes[cv_id], embedding=vectors[i].tolist()
                    )
                    cv_stmt = cv_stmt.on_conflict_do_update(
                        index_elements=[CvEmbedding.cv_id],
                        set_={
                            "content_hash": cv_stmt.excluded.content_hash,
                            "embedding": cv_stmt.excluded.embedding,
                            "updated_at": func.now(),
                        },
                    )
                    conn.execute(cv_stmt)

            distance = CvEmbedding.embedding.cosine_distance(job_vector.tolist()).label("distance")
            limit = max(1, min(top_k, len(cv_ids)))
            rows = conn.execute(
                select(CvEmbedding.cv_id, distance)
                .where(CvEmbedding.cv_id.in_(cv_ids))
                .order_by(distance.asc())
                .limit(limit)
            ).all()

        return [
            (candidates_by_id[row.cv_id], max(0.0, 1.0 - float(row.distance)))
            for row in rows
            if row.cv_id in candidates_by_id
        ]
    except Exception as exc:  # noqa: BLE001
        logging.warning("Classement pgvector impossible, repli sur FAISS: %s", exc)
        return None


def build_score(job: PreparedJob, cv: PreparedCv, similarity: float, rank: int) -> ScoreItem:
    strengths: List[str] = []
    weaknesses: List[str] = []

    keyword_hits = sorted(job.keyword_set.intersection(cv.keyword_set | cv.text_tokens))
    if keyword_hits:
        strengths.append(f"Mots-clés ({', '.join(keyword_hits[:5])})")
    else:
        weaknesses.append("Aucun mot-clé commun identifié")

    title_overlap = job.tokens.intersection(cv.title_tokens)
    if title_overlap:
        strengths.append(f"Titre proche ({', '.join(sorted(title_overlap)[:3])})")
    else:
        weaknesses.append("Titre éloigné du besoin")

    structure_bonus = 0.0
    structure_penalty = 0.0

    if cv.qualified is True:
        strengths.append("Profil déclaré qualifié pour le poste")
    elif cv.qualified is False:
        weaknesses.append("Profil déclaré non qualifié")
        structure_penalty += settings.qualification_penalty

    if job.jobtype and cv.jobtype:
        if overlap_text(job.jobtype, cv.jobtype):
            strengths.append("Type de contrat compatible")
            structure_bonus += settings.jobtype_weight
        else:
            weaknesses.append("Type de contrat différent")
            structure_penalty += settings.jobtype_weight

    if job.category and cv.category:
        if overlap_text(job.category, cv.category):
            strengths.append("Catégorie métier alignée")
            structure_bonus += settings.category_weight
        else:
            weaknesses.append("Catégorie métier différente")
            structure_penalty += settings.category_weight / 2

    if job.min_experience_years is not None and cv.experience_years is not None:
        experience_bonus, experience_penalty = compute_experience_adjustment(
            job.min_experience_years,
            cv.experience_years,
            settings.experience_weight,
        )
        if cv.experience_years >= job.min_experience_years:
            strengths.append(f"Expérience suffisante ({cv.experience_years:g} ans)")
        else:
            weaknesses.append(f"Expérience inférieure ({cv.experience_years:g} ans)")
        structure_bonus += experience_bonus
        structure_penalty += experience_penalty

    if job.salary_max is not None and cv.salary_expected_min is not None:
        if cv.salary_expected_min <= job.salary_max:
            strengths.append("Prétention salariale compatible")
            structure_bonus += settings.salary_weight
        else:
            weaknesses.append("Prétention salariale au-dessus du budget")
            structure_penalty += settings.salary_weight

    location_bonus = 0.0
    if job.location and cv.location:
        if job.location in cv.location or cv.location in job.location:
            strengths.append("Localisation compatible")
            location_bonus = settings.location_weight
        else:
            weaknesses.append("Localisation différente")

    base_score = max(0.0, similarity) * 70
    score = base_score + len(keyword_hits) * settings.keyword_weight
    if title_overlap:
        score += settings.title_weight
    score += location_bonus
    score += structure_bonus
    score -= structure_penalty
    score = float(max(0.0, min(100.0, score)))

    extra = {
        "vector_similarity": round(float(similarity), 4),
        "keyword_hits": keyword_hits,
        "rank": rank + 1,
        "cv_category": cv.category,
        "cv_jobtype": cv.jobtype,
        "cv_experience_years": cv.experience_years,
        "cv_salary_min": cv.salary_expected_min,
        "cv_salary_max": cv.salary_expected_max,
        "cv_qualified": cv.qualified,
        "score_breakdown": {
            "semantic": round(base_score, 4),
            "keyword_bonus": round(len(keyword_hits) * settings.keyword_weight, 4),
            "title_bonus": round(settings.title_weight if title_overlap else 0.0, 4),
            "location_bonus": round(location_bonus, 4),
            "structure_bonus": round(structure_bonus, 4),
            "structure_penalty": round(structure_penalty, 4),
        },
    }

    return ScoreItem(
        cv_id=cv.payload.id,
        score=round(score, 2),
        strengths=strengths,
        weaknesses=weaknesses,
        keywords=keyword_hits,
        extra=extra,
    )


@app.get("/health")
def healthcheck() -> dict:
    return {
        "status": "ok",
        "model": settings.sentence_model,
        "model_loaded": _model is not None,
        "model_cache": os.getenv("MODEL_CACHE", "/models"),
        "data_dir": str(settings.data_dir),
        "pgvector_enabled": _pgvector_ready,
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

    if not usable:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Aucun texte exploitable pour les CV")

    filtered_usable: List[PreparedCv] = []
    for cv in usable:
        ok, _ = passes_hard_filters(job, cv)
        if ok:
            filtered_usable.append(cv)

    candidates = filtered_usable if filtered_usable else usable

    ranked = rank_with_pgvector(job, payload.job.id, candidates, settings.top_k) if _pgvector_ready else None
    if ranked is None:
        ranked = rank_with_faiss(job, candidates, settings.top_k)

    scored_items: List[ScoreItem] = []
    for rank, (cv, sim) in enumerate(ranked):
        if sim < settings.min_similarity:
            continue
        scored_items.append(build_score(job, cv, sim, rank))

    if not scored_items and ranked:
        cv, sim = ranked[0]
        scored_items.append(build_score(job, cv, sim, 0))

    # Final deterministic ranking must follow final score, not raw embedding rank.
    scored_items.sort(
        key=lambda item: (
            -float(item.score),
            -float(item.extra.get("vector_similarity", 0.0)),
            -float(item.extra.get("cv_experience_years") or -1),
            int(item.cv_id),
        )
    )

    for final_rank, item in enumerate(scored_items, start=1):
        item.extra["rank"] = final_rank

    duration_ms = int((time.perf_counter() - started) * 1000)

    return ScoreResponse(job_id=payload.job.id, count=len(scored_items), duration_ms=duration_ms, results=scored_items)