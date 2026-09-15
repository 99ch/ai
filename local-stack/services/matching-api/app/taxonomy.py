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
    "Git": ["git", "bitbucket", "bitbuckets"],
    "Linux": ["linux"],
    "WordPress": ["wordpress", "wp"],
    "React": ["react", "react.js", "reactjs"],
    "Angular": ["angular", "angularjs"],
    # Pas d'alias "vue" seul : c'est un mot français très courant ("point de
    # vue", "en vue de", "revue") — faux positif confirmé chez AI Real-Time
    # (36673c6), corrigé de la même façon ici avant même d'avoir été observé
    # en prod chez nous.
    "Vue.js": ["vue.js", "vuejs"],
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


# Alias ROME courts (>= 2 caractères) qui collident avec des mots
# grammaticaux français très fréquents une fois le texte tokenisé — trouvé
# chez AI Real-Time sur le même fichier rome_skills_data.json (cd8e45e) :
# "son" -> canonique "Son" matche le possessif "son/sa/ses" dans n'importe
# quelle phrase ("...pour son équipe..."). Les alias 1 caractère ("c" -> "C")
# sont déjà exclus catégoriquement ci-dessous.
_ROME_ALIAS_STOPWORDS: frozenset[str] = frozenset({"son"})

# Libellés canoniques rencontrés dans NOTRE copie de rome_skills_data.json
# (vérifié) qui sont du vocabulaire professionnel générique plutôt que des
# compétences concrètes — une offre qui dit juste "bonne communication" ou
# "sens du service" ne devrait pas compter comme une compétence technique
# au même titre que "Docker" ou "SQL". Même liste/logique qu'AI Real-Time
# (a4f576f/61886a9), réduite aux entrées confirmées présentes dans ce
# fichier partagé (le reste de leur liste vient de leur propre dictionnaire
# _SKILLS, que nous n'avons pas).
#
# "Grande distribution" est un ajout à NOUS, pas un portage : absente de la
# liste d'AI Real-Time (leur commentaire dit explicitement que leur import
# ROME 8500+ entrées n'a pas été audité en entier, celle-ci n'a simplement
# jamais été rencontrée chez eux). Trouvée en auditant Keoni sur un
# échantillon d'offres réelles (2026-09-15) : 4 offres sur 5 testées
# partagent le même paragraphe passe-partout d'ESN ("nous accompagnons nos
# clients de l'industrie, banque & assurance, grande distribution &
# e-commerce...") en tête ou pied de texte — ce n'est jamais une exigence
# du poste, juste la liste des secteurs clients de l'agence, et avec
# seulement 3-4 compétences détectées par offre en moyenne, ce faux positif
# à lui seul pesait ~25 points de couverture sur un candidat par ailleurs
# bien aligné (cas réel audité : 45.5 au lieu des ~65+ attendus).
_GENERIC_SKILL_CANONICALS: frozenset[str] = frozenset({
    "Contrôle qualité",
    "Ecoute active",
    "Gestion du temps",
    "Grande distribution",
})


@lru_cache(maxsize=1)
def _load_lookup() -> Dict[str, str]:
    """alias replié -> libellé canonique.

    _TECH_SKILLS est chargé en premier et prioritaire (via setdefault, ROME
    ne peut jamais l'écraser) ; ROME ne fait que combler les trous. Le
    fichier ROME manquant/corrompu ne fait pas échouer le module.

    N'indexe que les alias explicitement déclarés, jamais le nom canonique
    lui-même : AI Real-Time indexait aussi le canonique comme alias
    implicite, et sur ce même fichier ROME (8508 entrées, souvent nommées
    d'un simple mot métier générique : "Distribution", "Qualité",
    "Management"...) ça faisait matcher n'importe quelle occurrence isolée
    de ce mot, sans rapport avec la compétence (corrigé chez eux en
    2d670be). Les alias explicites de rome_skills_data.json couvrent déjà
    la forme repliée du canonique quand c'est pertinent.
    """
    lookup: Dict[str, str] = {}

    for canonical, aliases in _TECH_SKILLS.items():
        for alias in aliases:
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
            if not isinstance(aliases, list):
                continue
            for alias in aliases:
                key = _fold(str(alias))
                if len(key) <= 1 or key in _ROME_ALIAS_STOPWORDS:
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
                # Vocabulaire professionnel générique (voir
                # _GENERIC_SKILL_CANONICALS) : les tokens sont bien
                # consommés (pas de rescan à une taille plus courte), mais
                # le "match" n'est jamais ajouté aux compétences détectées.
                if canonical not in _GENERIC_SKILL_CANONICALS and canonical not in seen:
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
