"""Tests de non-régression pour app/extraction.py.

Le cas ci-dessous correspond à un bug trouvé chez AI Real-Time (629a1bb,
validation sur ~1500 CV réels) sur le même genre d'extraction PDF/DOCX que
nous portons ici, et observé directement sur le CV utilisé tout au long de
cette fonctionnalité (titre "DÉVELOPPEUR WEB" rendu "D É V E L O P P E U R
W E B" par l'extraction PyMuPDF sur un template au style décoratif).
"""

from __future__ import annotations

from app.extraction import _collapse_letter_spacing, clean_text


def test_letter_spaced_heading_is_collapsed():
    assert _collapse_letter_spacing("C O M P É T E N C E S") == "COMPÉTENCES"
    assert _collapse_letter_spacing("D É V E LO P P E U R W E B") == "DÉVELOPPEURWEB"


def test_normal_prose_is_left_alone():
    assert _collapse_letter_spacing("Ceci est une phrase normale") == "Ceci est une phrase normale"
    # Mots d'une lettre légitimes dans une phrase normale (proportion trop faible pour déclencher).
    assert _collapse_letter_spacing("Il a dit à y aller") == "Il a dit à y aller"


def test_short_line_is_not_collapsed():
    # Sous le seuil de 4 tokens : jamais touché, même si tout est en lettres isolées.
    assert _collapse_letter_spacing("R et D") == "R et D"


def test_clean_text_applies_letter_spacing_collapse():
    result = clean_text("D É V E L O P P E U R W E B\nCompétences: Python, Docker")
    assert "DÉVELOPPEURWEB" in result
    assert "Python" in result
