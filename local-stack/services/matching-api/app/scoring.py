"""Formule de score CV/offre, portée depuis AI Real-Time (backend/app/services/matcher.py).

Keoni utilisait jusqu'ici une formule additive (base sémantique + bonus/malus
en points bruts). AI Real-Time utilise une moyenne pondérée, renormalisée sur
les seules composantes qui ont un vrai signal à comparer (`has_signal`), avec
un plafond de couverture skills/mots-clés — voir `_weights()` et
`match_parsed_documents()` dans le fichier source. Porté ici à l'identique
dans sa structure, avec les composantes adaptées aux données réellement
disponibles côté Keoni (pas d'extraction education/langues séparée par
exemple — ces composantes n'ont simplement jamais `has_signal=True` chez
Keoni et sont donc exclues de la moyenne, elles ne sont pas inventées).

Volontairement sans import lourd (pas de sentence-transformers/faiss/tika) :
la mesure de similarité sémantique est calculée ailleurs (main.py) et
seulement passée en paramètre ici, ce qui permet de tester cette formule
sans installer toute la pile ML (voir tests/test_scoring.py et
requirements-dev.txt).

Volontairement PAS porté depuis AI Real-Time (hors périmètre) :
- Les "scoring profiles" (job.scoring_profile) : Keoni n'a pas d'UI
  recruteur pour choisir un profil de pondération par offre.
- Le mécanisme de "core keyword coverage" (répétition de mots-clés,
  détection de titre à alternatives) : conçu pour un textarea recruteur
  "Mots Clés.docx" collé ligne par ligne, qui n'existe pas dans le
  formulaire WordPress de Keoni (un seul champ mots-clés, déjà dédupliqué).
- L'inférence de séniorité depuis le titre ("expert"/"senior"/"junior") :
  amélioration annexe de la composante expérience, pas la logique centrale.
- Le crédit sémantique partiel sur les compétences non matchées littéralement
  (embeddings de compétences) : Keoni n'a pas encore de module d'embeddings
  de compétences dédié comme AI Real-Time (`embeddings.best_skill_similarities`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

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
    "aux",
    "von",
    "und",
    "pour",
    "entre",
    "dans",
    "from",
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


def overlap_text(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    return bool(tokenize(a) & tokenize(b))


@dataclass(slots=True)
class PreparedJob:
    text: str
    semantic_text: str
    tokens: set[str]
    keywords: List[str]
    keyword_set: set[str]
    skills_canonical: set[str]
    location: str
    category: str
    jobtype: str
    min_experience_years: Optional[float]
    salary_min: Optional[float]
    salary_max: Optional[float]


@dataclass(slots=True)
class PreparedCv:
    payload: object
    text: str
    text_tokens: set[str]
    title_tokens: set[str]
    keywords: List[str]
    keyword_set: set[str]
    skills_canonical: set[str]
    location: str
    category: str
    jobtype: str
    experience_years: Optional[float]
    salary_expected_min: Optional[float]
    salary_expected_max: Optional[float]
    qualified: Optional[bool]


# ── Poids ──────────────────────────────────────────────────────────────────
#
# Mêmes ordres de grandeur que _DEFAULT_W chez AI Real-Time (semantic=0.10,
# skills=0.40, priority_keywords=0.40, experience=0.20, education=0.08,
# languages=0.05, contract=0.05) : Keoni n'a pas de composantes
# education/languages séparées, remplacées ici par category/location, des
# signaux structurels du même ordre d'importance secondaire dans le domaine
# recrutement de Keoni. `salary` et `qualification` n'existent pas chez AI
# Real-Time (pas de notion de prétention salariale ni de "qualifié déclaré"
# dans leur modèle) ; ajoutés avec un poids modeste, du même ordre que
# jobtype/location, plutôt que de les supprimer silencieusement.
DEFAULT_WEIGHTS: dict[str, float] = {
    "semantic": 0.10,
    "skills": 0.35,
    "keywords": 0.35,
    "experience": 0.20,
    "jobtype": 0.05,
    "category": 0.08,
    "location": 0.05,
    "salary": 0.05,
    "qualification": 0.10,
}

# Plafond de couverture skills/mots-clés : même valeur et même mécanisme que
# _SKILL_CAP_FLOOR chez AI Real-Time (matcher.py), calibrée par eux sur un
# jeu de validation de 16 CV / 1 offre avec cible humaine indépendante par
# paire. Keoni n'a pas encore son propre jeu de validation équivalent, donc
# on part de leur valeur mesurée plutôt que d'un chiffre choisi au hasard.
SKILL_CAP_FLOOR = 0.30

# Zones d'expérience : portées à l'identique depuis AI Real-Time matcher.py
# (calibration du 2026-09-11 sur cas de production réel) — voir le
# commentaire historique dans matcher.py::_experience_zone_score pour le
# raisonnement (un poste "au moins N ans" est un plancher, pas une fenêtre :
# plus d'expérience que le plancher n'est jamais en soi un problème jusqu'à
# un multiple raisonnable, au-delà duquel le risque de surqualification
# dégrade progressivement le score plutôt qu'une chute brutale).
EXPERIENCE_COMFORTABLE_OVER_RATIO = 2.0
EXPERIENCE_SEVERE_OVER_RATIO = 4.0
EXPERIENCE_SEVERE_OVER_FLOOR = 0.85


def experience_zone_score(cv_years: float, job_years: float) -> float:
    """Calcul de zone pur (inferieur / egal / legerement superieur / trop
    superieur), porté à l'identique depuis AI Real-Time. Suppose
    cv_years > 0 et job_years > 0 (voir experience_component)."""
    if cv_years == job_years:
        return 1.0
    if cv_years > job_years:
        ratio = cv_years / job_years
        if ratio <= EXPERIENCE_COMFORTABLE_OVER_RATIO:
            return 1.0
        if ratio >= EXPERIENCE_SEVERE_OVER_RATIO:
            return EXPERIENCE_SEVERE_OVER_FLOOR
        span = EXPERIENCE_SEVERE_OVER_RATIO - EXPERIENCE_COMFORTABLE_OVER_RATIO
        progress = (ratio - EXPERIENCE_COMFORTABLE_OVER_RATIO) / span
        return 1.0 - progress * (1.0 - EXPERIENCE_SEVERE_OVER_FLOOR)
    shortfall = (job_years - cv_years) / job_years
    return max(0.0, 1.0 - shortfall)


# ── Composantes structurées ───────────────────────────────────────────────
#
# Chaque fonction retourne (valeur 0-1, has_signal). has_signal=False quand
# le score neutre/pénalité est dû à une INFORMATION MANQUANTE plutôt qu'à
# une vraie comparaison (ex : l'offre ne précise pas de type de contrat) —
# même contrat que les fonctions `_*_score` de matcher.py. Ces composantes
# sont exclues de la moyenne pondérée quand has_signal=False (voir
# compute_final_score), pour qu'une extraction manquante ne fasse pas
# chuter le score à pleine pondération au lieu de ne simplement pas compter.


def skills_component(job: PreparedJob, cv: PreparedCv) -> Tuple[float, bool, List[str]]:
    """Couverture des compétences de l'offre (taxonomie ROME/technique) par
    le CV. Équivalent Keoni de `_skill_score` chez AI Real-Time (sans le
    crédit sémantique partiel sur les compétences non matchées, hors
    périmètre — voir le docstring du module)."""
    if not job.skills_canonical:
        return 0.5, False, []  # offre sans compétence identifiable à comparer
    if not cv.skills_canonical:
        return 0.0, False, []  # rien d'extrait côté CV pour comparer
    hits = sorted(job.skills_canonical & cv.skills_canonical)
    coverage = len(hits) / len(job.skills_canonical)
    return min(1.0, coverage), True, hits


def keywords_component(job: PreparedJob, cv: PreparedCv) -> Tuple[float, bool, List[str]]:
    """Couverture des mots-clés tapés par le recruteur (champ WP
    "keywords"). Équivalent Keoni de `_priority_keyword_score` chez AI
    Real-Time : un mot-clé tapé à la main par le recruteur joue le même
    rôle que leur liste de mots-clés prioritaires curatée. has_signal
    uniquement quand l'offre a des mots-clés (même règle que chez eux :
    "only counted when the job has priority keywords")."""
    if not job.keyword_set:
        return 0.5, False, []
    cv_terms = cv.keyword_set | cv.text_tokens
    hits = sorted(job.keyword_set & cv_terms)
    coverage = len(hits) / len(job.keyword_set)
    return min(1.0, coverage), True, hits


def experience_component(job: PreparedJob, cv: PreparedCv) -> Tuple[float, bool]:
    job_y = job.min_experience_years or 0.0
    cv_y = cv.experience_years or 0.0
    if job_y <= 0 and cv_y <= 0:
        return 0.5, False  # aucune année extraite ni côté offre ni côté CV
    if job_y <= 0:
        return 0.75, False  # offre sans exigence d'expérience à comparer
    if cv_y <= 0:
        return 0.2, False  # expérience du CV non extraite
    return experience_zone_score(cv_y, job_y), True


def jobtype_component(job: PreparedJob, cv: PreparedCv) -> Tuple[float, bool]:
    if not job.jobtype or not cv.jobtype:
        return 0.5, False
    return (1.0 if overlap_text(job.jobtype, cv.jobtype) else 0.0), True


def category_component(job: PreparedJob, cv: PreparedCv) -> Tuple[float, bool]:
    if not job.category or not cv.category:
        return 0.5, False
    return (1.0 if overlap_text(job.category, cv.category) else 0.0), True


def location_component(job: PreparedJob, cv: PreparedCv) -> Tuple[float, bool]:
    if not job.location or not cv.location:
        return 0.5, False
    return (1.0 if (job.location in cv.location or cv.location in job.location) else 0.0), True


def salary_component(job: PreparedJob, cv: PreparedCv) -> Tuple[float, bool]:
    if job.salary_max is None or cv.salary_expected_min is None:
        return 0.5, False
    return (1.0 if cv.salary_expected_min <= job.salary_max else 0.0), True


def qualification_component(cv: PreparedCv) -> Tuple[float, bool]:
    if cv.qualified is None:
        return 0.5, False
    return (1.0 if cv.qualified else 0.0), True


@dataclass(slots=True)
class ScoreResult:
    score: float  # 0-100
    semantic: float
    skill_hits: List[str] = field(default_factory=list)
    keyword_hits: List[str] = field(default_factory=list)
    breakdown: dict = field(default_factory=dict)
    low_confidence_components: List[str] = field(default_factory=list)
    weights: dict = field(default_factory=dict)


def compute_final_score(
    job: PreparedJob,
    cv: PreparedCv,
    similarity: float,
    rerank_score: Optional[float] = None,
    weights: Optional[dict[str, float]] = None,
) -> ScoreResult:
    """Moyenne pondérée renormalisée sur les composantes ayant un vrai
    signal, plus plafond de couverture skills/mots-clés — même structure
    que `match_parsed_documents()` chez AI Real-Time.

    `semantic` n'a pas de has_signal : le cross-encoder produit toujours
    une comparaison (réelle, ou un repli neutre à 0.5 s'il est
    indisponible), donc il compte toujours — même règle que chez eux.
    """
    w = dict(weights) if weights is not None else dict(DEFAULT_WEIGHTS)

    semantic = max(0.0, min(1.0, rerank_score if rerank_score is not None else similarity))

    skills_val, skills_ok, skill_hits = skills_component(job, cv)
    keywords_val, keywords_ok, keyword_hits = keywords_component(job, cv)
    experience_val, experience_ok = experience_component(job, cv)
    jobtype_val, jobtype_ok = jobtype_component(job, cv)
    category_val, category_ok = category_component(job, cv)
    location_val, location_ok = location_component(job, cv)
    salary_val, salary_ok = salary_component(job, cv)
    qualification_val, qualification_ok = qualification_component(cv)

    structured = (
        ("skills", skills_val, skills_ok),
        ("keywords", keywords_val, keywords_ok),
        ("experience", experience_val, experience_ok),
        ("jobtype", jobtype_val, jobtype_ok),
        ("category", category_val, category_ok),
        ("location", location_val, location_ok),
        ("salary", salary_val, salary_ok),
        ("qualification", qualification_val, qualification_ok),
    )

    weighted_sum = w["semantic"] * semantic
    weight_total = w["semantic"]
    for name, value, ok in structured:
        if ok:
            weighted_sum += w[name] * value
            weight_total += w[name]

    final = weighted_sum / weight_total if weight_total > 0 else 0.5
    final = max(0.0, min(1.0, final))

    if skills_ok:
        final = min(final, SKILL_CAP_FLOOR + (1 - SKILL_CAP_FLOOR) * skills_val)
    if keywords_ok:
        final = min(final, SKILL_CAP_FLOOR + (1 - SKILL_CAP_FLOOR) * keywords_val)

    breakdown = {
        "semantic": round(semantic, 4),
        "skills": round(skills_val, 4) if skills_ok else None,
        "keywords": round(keywords_val, 4) if keywords_ok else None,
        "experience": round(experience_val, 4) if experience_ok else None,
        "jobtype": round(jobtype_val, 4) if jobtype_ok else None,
        "category": round(category_val, 4) if category_ok else None,
        "location": round(location_val, 4) if location_ok else None,
        "salary": round(salary_val, 4) if salary_ok else None,
        "qualification": round(qualification_val, 4) if qualification_ok else None,
    }
    low_confidence = [name for name, _value, ok in structured if not ok]

    return ScoreResult(
        score=round(final * 100, 2),
        semantic=semantic,
        skill_hits=skill_hits,
        keyword_hits=keyword_hits,
        breakdown=breakdown,
        low_confidence_components=low_confidence,
        weights=w,
    )
