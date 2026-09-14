"""Normalisation de compétences, sur le même principe à deux couches qu'AI
Real-Time : un petit dictionnaire de synonymes techniques faits main
(prioritaire), complété par le référentiel ROME (France Travail) comme
couche de repli plus large.

Constat en implémentant ceci : le référentiel ROME "savoir" couvre des
compétences métier généralistes ("Développement de logiciels", "Architecture
web"...) mais quasiment aucun nom de techno concret (pas de "JavaScript",
"Python", "MongoDB"...). Sans la couche _TECH_SKILLS ci-dessous, ce module
serait de peu d'utilité sur les offres IT de Keoni — d'où son ajout, pour
que "JS"/"JavaScript" ou "Dev web"/"Développeur Web" soient bien reconnus
comme la même compétence.

On n'implémente pas la couche ESCO/FAISS d'AI Real-Time (CSV à télécharger
manuellement derrière un CAPTCHA, hors scope ici).

rome_skills_data.json est un export ouvert du référentiel ROME 4.0
("savoir"), scope "3DS MAX" -> ["3ds max"] : libellé canonique -> alias.
"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

_ROME_SKILLS_PATH = Path(__file__).with_name("data") / "rome_skills_data.json"
_TOKEN_RE = re.compile(r"[^\s,;/()|'’]+")
_MAX_NGRAM = 5

# Synonymes techniques courants, absents du référentiel ROME "savoir".
# Volontairement modeste (couvre le vocabulaire vu sur les offres/CV Keoni
# jusqu'ici) : à étendre au fil de l'eau plutôt que viser l'exhaustivité.
_TECH_SKILLS: Dict[str, List[str]] = {
    "JavaScript": ["js", "javascript", "ecmascript"],
    "TypeScript": ["ts", "typescript"],
    "Node.js": ["nodejs", "node.js", "node js", "node"],
    "PHP": ["php"],
    "Python": ["python", "py"],
    "Java": ["java"],
    "C#": ["c#", "csharp", "c sharp"],
    ".NET": [".net", "dotnet", "asp.net"],
    "HTML5": ["html", "html5"],
    "CSS3": ["css", "css3"],
    "SQL": ["sql"],
    "MySQL": ["mysql"],
    "PostgreSQL": ["postgresql", "postgres"],
    "MongoDB": ["mongodb", "mongo"],
    "Docker": ["docker"],
    "Kubernetes": ["kubernetes", "k8s"],
    "Git": ["git"],
    "Linux": ["linux"],
    "WordPress": ["wordpress", "wp"],
    "React": ["react", "react.js", "reactjs"],
    "Angular": ["angular", "angularjs"],
    "Vue.js": ["vue", "vue.js", "vuejs"],
    "jQuery": ["jquery"],
    "Bootstrap": ["bootstrap"],
    "Symfony": ["symfony"],
    "Laravel": ["laravel"],
    "AWS": ["aws", "amazon web services"],
    "DevOps": ["devops"],
    "CI/CD": ["ci/cd", "ci cd", "cicd", "integration continue"],
    "Développeur Web": ["dev web", "developpeur web", "web developer"],
}


def _fold(value: str) -> str:
    """Minuscule + suppression des accents, pour un lookup insensible à la casse/accentuation."""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.lower().strip()


@lru_cache(maxsize=1)
def _load_lookup() -> Dict[str, str]:
    """alias replié -> libellé canonique.

    _TECH_SKILLS est chargé en premier et prioritaire (via setdefault, ROME
    ne peut jamais l'écraser) ; ROME ne fait que combler les trous. Le
    fichier ROME manquant/corrompu ne fait pas échouer le module.
    """
    lookup: Dict[str, str] = {}

    for canonical, aliases in _TECH_SKILLS.items():
        for alias in [canonical, *aliases]:
            key = _fold(alias)
            if len(key) <= 1:
                continue
            lookup.setdefault(key, canonical)

    if _ROME_SKILLS_PATH.is_file():
        try:
            raw = json.loads(_ROME_SKILLS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}

        for canonical, aliases in raw.items():
            candidates = [canonical, *aliases] if isinstance(aliases, list) else [canonical]
            for alias in candidates:
                key = _fold(str(alias))
                if len(key) <= 1:
                    continue
                lookup.setdefault(key, canonical)

    return lookup


def normalize_skill(term: str) -> str | None:
    """Libellé canonique ROME pour un terme isolé, ou None si inconnu."""
    return _load_lookup().get(_fold(term))


def find_skills(text: str, max_results: int = 50) -> List[str]:
    """Compétences ROME détectées dans un texte libre (offre ou CV), dédupliquées,
    dans l'ordre de première apparition. Scan glouton du plus long n-gramme au
    plus court pour éviter qu'un match partiel ne casse un libellé multi-mots.
    """
    lookup = _load_lookup()
    if not lookup or not text:
        return []

    raw_tokens = _TOKEN_RE.findall(text.lower())
    # Un mot en fin de phrase garde son "." ("Docker.") : on l'enlève en
    # bordure sans toucher aux tokens qui en ont légitimement un ("node.js").
    tokens = [tok for tok in (t.strip(".,;:!?") for t in raw_tokens) if tok]
    if not tokens:
        return []

    found: List[str] = []
    seen: set[str] = set()
    i = 0
    n = len(tokens)

    while i < n:
        matched = False
        for size in range(min(_MAX_NGRAM, n - i), 0, -1):
            candidate = " ".join(tokens[i : i + size])
            canonical = lookup.get(_fold(candidate))
            if canonical:
                if canonical not in seen:
                    seen.add(canonical)
                    found.append(canonical)
                    if len(found) >= max_results:
                        return found
                i += size
                matched = True
                break
        if not matched:
            i += 1

    return found
