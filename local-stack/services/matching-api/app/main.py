from __future__ import annotations

import hashlib
import logging
import math
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
from sentence_transformers import CrossEncoder, SentenceTransformer
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from tika import parser

from app import extraction
from app.db import get_engine, init_db
from app.models import CvEmbedding, JobEmbedding
from app.scoring import (
    DEFAULT_WEIGHTS,
    PreparedCv,
    PreparedJob,
    ScoreResult,
    compute_final_score,
    normalize_whitespace,
    overlap_text,
    tokenize,
)
from app.taxonomy import find_skills

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(title="Keoni Matching API", version="0.2.0")


@dataclass(slots=True)
class Settings:
    sentence_model: str = os.getenv("SENTENCE_MODEL", "intfloat/multilingual-e5-base")
    top_k: int = int(os.getenv("MATCHING_TOP_K", "200"))
    min_similarity: float = float(os.getenv("MATCHING_MIN_SIMILARITY", "0.2"))
    # Poids de la moyenne pondérée renormalisée — même logique que _DEFAULT_W
    # chez AI Real-Time (matcher.py), voir app/scoring.py::DEFAULT_WEIGHTS
    # pour le détail de chaque composante et le mapping vs leurs 6 signaux
    # d'origine. Remplace l'ancienne formule additive en points bruts.
    w_semantic: float = float(os.getenv("MATCHING_W_SEMANTIC", str(DEFAULT_WEIGHTS["semantic"])))
    w_skills: float = float(os.getenv("MATCHING_W_SKILLS", str(DEFAULT_WEIGHTS["skills"])))
    w_keywords: float = float(os.getenv("MATCHING_W_KEYWORDS", str(DEFAULT_WEIGHTS["keywords"])))
    w_experience: float = float(os.getenv("MATCHING_W_EXPERIENCE", str(DEFAULT_WEIGHTS["experience"])))
    w_jobtype: float = float(os.getenv("MATCHING_W_JOBTYPE", str(DEFAULT_WEIGHTS["jobtype"])))
    w_category: float = float(os.getenv("MATCHING_W_CATEGORY", str(DEFAULT_WEIGHTS["category"])))
    w_location: float = float(os.getenv("MATCHING_W_LOCATION", str(DEFAULT_WEIGHTS["location"])))
    w_salary: float = float(os.getenv("MATCHING_W_SALARY", str(DEFAULT_WEIGHTS["salary"])))
    w_qualification: float = float(os.getenv("MATCHING_W_QUALIFICATION", str(DEFAULT_WEIGHTS["qualification"])))
    hard_filter_jobtype: bool = os.getenv("MATCHING_HARD_FILTER_JOBTYPE", "1") == "1"
    hard_filter_qualification: bool = os.getenv("MATCHING_HARD_FILTER_QUALIFICATION", "1") == "1"
    embed_batch_size: int = int(os.getenv("EMBED_BATCH_SIZE", "32"))
    preload_model: bool = os.getenv("MATCHING_PRELOAD_MODEL", "1") == "1"
    data_dir: Path = Path(os.getenv("DATA_DIR", "/data/cv_raw"))
    file_fetch_timeout_seconds: int = int(os.getenv("MATCHING_FILE_FETCH_TIMEOUT", "15"))
    file_fetch_max_bytes: int = int(os.getenv("MATCHING_FILE_FETCH_MAX_BYTES", str(20 * 1024 * 1024)))
    crossencoder_enabled: bool = os.getenv("MATCHING_CROSSENCODER_ENABLED", "1") == "1"
    crossencoder_model: str = os.getenv(
        "MATCHING_CROSSENCODER_MODEL", "antoinelouis/crossencoder-camembert-large-mmarcoFR"
    )
    crossencoder_top_k: int = int(os.getenv("MATCHING_CROSSENCODER_TOP_K", "30"))
    tika_timeout_seconds: int = int(os.getenv("MATCHING_TIKA_TIMEOUT_SECONDS", "30"))


settings = Settings()
_model: Optional[SentenceTransformer] = None
_model_lock = Lock()
_cross_encoder: Optional[CrossEncoder] = None
_cross_encoder_disabled = False  # settings.crossencoder_enabled == False -- permanent, délibéré
_cross_encoder_last_failure: Optional[float] = None  # time.monotonic() du dernier échec de chargement
_CROSS_ENCODER_RETRY_COOLDOWN_S = 300
_cross_encoder_lock = Lock()
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


@app.on_event("startup")
def warmup_cross_encoder_model() -> None:
    """Précharge aussi le cross-encoder au démarrage, pas seulement l'embedding.

    AI Real-Time n'avait qu'un warm-up pour Docling au départ ; tous les
    autres modèles (dont le cross-encoder) chargeaient au premier usage réel
    — un premier document après (re)démarrage payait le coût de chargement
    à froid de chaque modèle touché, en série, dans la requête elle-même
    (150+ s observés en production, au-delà des timeouts du frontend).
    get_cross_encoder() gère déjà ses propres erreurs (retry/cooldown) ; ce
    warm-up ne fait que déclencher le même chemin plus tôt.
    """
    if not settings.preload_model or not settings.crossencoder_enabled:
        return

    started = time.perf_counter()
    model = get_cross_encoder()
    if model is not None:
        try:
            model.predict([("warmup", "warmup")])
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            logging.info("Cross-encoder preloaded and warmed in %d ms", elapsed_ms)
        except Exception as exc:  # noqa: BLE001
            logging.warning("Cross-encoder warmup predict failed: %s", exc)


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
    # Pour .pdf/.docx/.txt, l'extraction consciente des colonnes (portée
    # depuis AI Real-Time) donne une bien meilleure fidélité qu'une lecture
    # naïve, en particulier sur les CV à deux colonnes (barre latérale +
    # corps principal) — voir app/extraction.py. Tika reste le repli pour
    # ces formats en cas d'échec, et le seul chemin pour les autres formats.
    if path.suffix.lower() in {".pdf", ".docx", ".txt"}:
        column_aware_text = extraction.extract_text(path)
        if column_aware_text:
            return normalize_whitespace(column_aware_text)
        logging.warning("Extraction consciente des colonnes vide pour %s, repli sur Tika", path)

    try:
        # La lib tika met déjà un timeout par défaut (60s) sur la requête HTTP
        # au serveur Tika local, mais pas sur la phase de démarrage de la JVM
        # avant celle-ci (on l'a vu échouer/retenter ~15-20s en test) — le
        # rendre explicite et plus court évite qu'un fichier pathologique ne
        # bloque une requête /score entière, dans le même esprit que le
        # timeout OCR déjà porté d'AI Real-Time (5dd92c6) dans extraction.py.
        parsed = parser.from_file(
            str(path), requestOptions={"timeout": settings.tika_timeout_seconds}
        )
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
    # Texte dédié au cross-encoder, en langage naturel uniquement : lui coller
    # la liste de mots-clés bruts (utile pour l'embedding, tolérant au
    # sac-de-mots) a fait chuter un score cross-encoder de 0.56 à 0.005 sur un
    # cas réel — le cross-encoder juge la cohérence de la phrase, pas juste
    # la présence de mots. Repli sur `text` si les champs naturels sont vides.
    semantic_parts = [job.title, job.description, job.content, job.excerpt]
    semantic_text = normalize_whitespace(" ".join(filter(None, semantic_parts))) or text
    location = (job.location or meta.get("location") or "").lower()
    tokens = tokenize(f"{job.title} {job.description}")
    category = normalized_text(find_first(meta, ["jobcategory_text", "category_text", "job_category", "category"]))
    jobtype = normalized_text(find_first(meta, ["jobtype_text", "job_type", "type", "jobtype"]))
    min_experience_years = parse_float(find_first(meta, ["experience", "min_experience", "required_experience"]))

    salary_min = parse_float(find_first(meta, ["salaryfrom", "salary_min", "salary_from"]))
    salary_max = parse_float(find_first(meta, ["salaryto", "salary_max", "salary_to", "tjm", "salary"]))

    return PreparedJob(
        text=text,
        semantic_text=semantic_text,
        tokens=tokens,
        keywords=keywords,
        keyword_set=set(keywords),
        skills_canonical=set(find_skills(text)),
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
        skills_canonical=set(find_skills(text)),
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


def get_cross_encoder() -> Optional[CrossEncoder]:
    """Charge le cross-encoder paresseusement, en retentant après un cooldown
    plutôt qu'en mettant en cache un échec pour toujours.

    Constaté chez AI Real-Time en production : la chaîne d'import du modèle
    (sentence_transformers -> transformers -> torch -> sympy) est assez
    lourde pour qu'un simple accroc transitoire au tout premier appel de
    scoring (contention CPU/mémoire au cold-start, disque lent) la fasse
    échouer une fois -- le même import réussit sans problème peu après.
    Mettre en cache cet échec unique comme un sentinel "indisponible"
    permanent aplatissait silencieusement la composante sémantique de chaque
    match (poids important dans le score final) à un 0.5 neutre jusqu'au
    prochain redémarrage. Un retry borné permet de s'auto-corriger.

    crossencoder_enabled=False reste un opt-out permanent et délibéré ; seul
    un échec de chargement déclenche le comportement de retry.
    """
    global _cross_encoder, _cross_encoder_disabled, _cross_encoder_last_failure

    if _cross_encoder is not None:
        return _cross_encoder
    if _cross_encoder_disabled:
        return None

    with _cross_encoder_lock:
        if _cross_encoder is not None:
            return _cross_encoder
        if _cross_encoder_disabled:
            return None

        if not settings.crossencoder_enabled:
            _cross_encoder_disabled = True
            return None

        now = time.monotonic()
        if (
            _cross_encoder_last_failure is not None
            and now - _cross_encoder_last_failure < _CROSS_ENCODER_RETRY_COOLDOWN_S
        ):
            return None

        try:
            logging.info("Loading cross-encoder model %s", settings.crossencoder_model)
            _cross_encoder = CrossEncoder(settings.crossencoder_model)
            _cross_encoder_last_failure = None
        except Exception as exc:  # noqa: BLE001
            _cross_encoder_last_failure = now
            logging.warning(
                "Cross-encoder indisponible (%s), rerank neutre à 0.5, nouvel essai dans %ss",
                exc,
                _CROSS_ENCODER_RETRY_COOLDOWN_S,
            )

    return _cross_encoder


def chunk_text(value: str, max_chars: int = 800, max_chunks: int = 8) -> List[str]:
    value = value.strip()
    if not value:
        return [""]
    chunks = [value[i : i + max_chars] for i in range(0, len(value), max_chars)]
    return chunks[:max_chunks] or [""]


def cross_encode_best(query: str, document: str) -> float:
    """Score sémantique fin d'une paire (offre, CV), 0-1 (sigmoïde du logit brut).

    Les deux textes sont découpés en fenêtres de ≤800 caractères (8 max
    chacun) pour rester robuste sur les CV longs ; on garde la meilleure
    paire de fenêtres plutôt qu'une moyenne, pour ne pas diluer un bon match
    localisé dans un texte par ailleurs peu pertinent.
    """
    model = get_cross_encoder()
    if model is None:
        return 0.5

    pairs = [(q, d) for q in chunk_text(query) for d in chunk_text(document)]

    try:
        raw_scores = model.predict(pairs)
    except Exception as exc:  # noqa: BLE001
        logging.warning("Cross-encoder predict a échoué: %s", exc)
        return 0.5

    if len(raw_scores) == 0:
        return 0.5

    best_raw = float(np.max(raw_scores))
    return 1.0 / (1.0 + math.exp(-best_raw))


def rerank_with_cross_encoder(
    job: PreparedJob, ranked: List[Tuple[PreparedCv, float]], top_k: int
) -> dict[int, float]:
    """Score cross-encoder pour le top-k de `ranked` (déjà trié par similarité
    d'embedding pgvector/FAISS) ; on ne raffine que les meilleurs candidats
    pour maîtriser le coût CPU. Retourne {cv_id: score} pour ce sous-ensemble.
    """
    if not settings.crossencoder_enabled or not ranked:
        return {}

    limit = max(0, min(top_k, len(ranked)))
    return {cv.payload.id: cross_encode_best(job.semantic_text, cv.text) for cv, _sim in ranked[:limit]}


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


def active_weights() -> dict[str, float]:
    return {
        "semantic": settings.w_semantic,
        "skills": settings.w_skills,
        "keywords": settings.w_keywords,
        "experience": settings.w_experience,
        "jobtype": settings.w_jobtype,
        "category": settings.w_category,
        "location": settings.w_location,
        "salary": settings.w_salary,
        "qualification": settings.w_qualification,
    }


def build_score(
    job: PreparedJob, cv: PreparedCv, similarity: float, rank: int, rerank_score: Optional[float] = None
) -> ScoreItem:
    # Moyenne pondérée renormalisée sur les composantes ayant un vrai signal
    # + plafond de couverture skills/mots-clés — même logique que
    # match_parsed_documents() chez AI Real-Time (matcher.py). Voir
    # app/scoring.py pour le détail de chaque composante.
    result: ScoreResult = compute_final_score(job, cv, similarity, rerank_score, active_weights())

    strengths: List[str] = []
    weaknesses: List[str] = []
    low = set(result.low_confidence_components)

    if result.keyword_hits:
        strengths.append(f"Mots-clés ({', '.join(result.keyword_hits[:5])})")
    elif job.keyword_set:
        weaknesses.append("Aucun mot-clé commun identifié")

    if result.skill_hits:
        strengths.append(f"Compétences reconnues ({', '.join(result.skill_hits[:5])})")
    elif job.skills_canonical:
        weaknesses.append("Aucune compétence reconnue en commun")

    title_overlap = job.tokens.intersection(cv.title_tokens)
    if title_overlap:
        strengths.append(f"Titre proche ({', '.join(sorted(title_overlap)[:3])})")

    if "qualification" not in low:
        if cv.qualified:
            strengths.append("Profil déclaré qualifié pour le poste")
        else:
            weaknesses.append("Profil déclaré non qualifié")

    if "jobtype" not in low:
        if result.breakdown["jobtype"] == 1.0:
            strengths.append("Type de contrat compatible")
        else:
            weaknesses.append("Type de contrat différent")

    if "category" not in low:
        if result.breakdown["category"] == 1.0:
            strengths.append("Catégorie métier alignée")
        else:
            weaknesses.append("Catégorie métier différente")

    if "experience" not in low:
        if cv.experience_years >= job.min_experience_years:
            strengths.append(f"Expérience suffisante ({cv.experience_years:g} ans)")
        else:
            weaknesses.append(f"Expérience inférieure ({cv.experience_years:g} ans)")

    if "salary" not in low:
        if result.breakdown["salary"] == 1.0:
            strengths.append("Prétention salariale compatible")
        else:
            weaknesses.append("Prétention salariale au-dessus du budget")

    if "location" not in low:
        if result.breakdown["location"] == 1.0:
            strengths.append("Localisation compatible")
        else:
            weaknesses.append("Localisation différente")

    extra = {
        "vector_similarity": round(float(similarity), 4),
        "cross_encoder_score": round(float(rerank_score), 4) if rerank_score is not None else None,
        "keyword_hits": result.keyword_hits,
        "skill_hits": result.skill_hits,
        "rank": rank + 1,
        "cv_category": cv.category,
        "cv_jobtype": cv.jobtype,
        "cv_experience_years": cv.experience_years,
        "cv_salary_min": cv.salary_expected_min,
        "cv_salary_max": cv.salary_expected_max,
        "cv_qualified": cv.qualified,
        "weights": result.weights,
        "score_breakdown": result.breakdown,
        "low_confidence_components": result.low_confidence_components,
    }

    return ScoreItem(
        cv_id=cv.payload.id,
        score=result.score,
        strengths=strengths,
        weaknesses=weaknesses,
        keywords=result.keyword_hits,
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
        "crossencoder_enabled": settings.crossencoder_enabled,
        "crossencoder_model": settings.crossencoder_model if settings.crossencoder_enabled else None,
        "crossencoder_loaded": _cross_encoder is not None,
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

    # Le cross-encoder affine seulement le top-k retenu par pgvector/FAISS ;
    # ranked reste trié par similarité d'embedding, pas par ce score.
    rerank_scores = rerank_with_cross_encoder(job, ranked, settings.crossencoder_top_k)

    scored_items: List[ScoreItem] = []
    for rank, (cv, sim) in enumerate(ranked):
        if sim < settings.min_similarity:
            continue
        scored_items.append(build_score(job, cv, sim, rank, rerank_scores.get(cv.payload.id)))

    if not scored_items and ranked:
        cv, sim = ranked[0]
        scored_items.append(build_score(job, cv, sim, 0, rerank_scores.get(cv.payload.id)))

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