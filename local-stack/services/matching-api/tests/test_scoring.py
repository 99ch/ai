import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.scoring import (  # noqa: E402
    DEFAULT_WEIGHTS,
    PreparedCv,
    PreparedJob,
    SKILL_CAP_FLOOR,
    category_component,
    compute_final_score,
    experience_component,
    experience_zone_score,
    jobtype_component,
    keywords_component,
    location_component,
    qualification_component,
    salary_component,
    skills_component,
)


def make_job(**overrides) -> PreparedJob:
    defaults = dict(
        text="",
        semantic_text="",
        tokens=set(),
        keywords=[],
        keyword_set=set(),
        skills_canonical=set(),
        location="",
        category="",
        jobtype="",
        min_experience_years=None,
        salary_min=None,
        salary_max=None,
    )
    defaults.update(overrides)
    return PreparedJob(**defaults)


def make_cv(**overrides) -> PreparedCv:
    defaults = dict(
        payload=object(),
        text="",
        text_tokens=set(),
        title_tokens=set(),
        keywords=[],
        keyword_set=set(),
        skills_canonical=set(),
        location="",
        category="",
        jobtype="",
        experience_years=None,
        salary_expected_min=None,
        salary_expected_max=None,
        qualified=None,
    )
    defaults.update(overrides)
    return PreparedCv(**defaults)


# ── skills_component ────────────────────────────────────────────────────


def test_skills_component_no_signal_when_job_has_no_skills():
    job = make_job(skills_canonical=set())
    cv = make_cv(skills_canonical={"Python"})
    value, ok, hits = skills_component(job, cv)
    assert (value, ok, hits) == (0.5, False, [])


def test_skills_component_no_signal_when_cv_has_no_skills():
    job = make_job(skills_canonical={"Python"})
    cv = make_cv(skills_canonical=set())
    value, ok, hits = skills_component(job, cv)
    assert (value, ok, hits) == (0.0, False, [])


def test_skills_component_partial_coverage():
    job = make_job(skills_canonical={"Python", "SQL", "Docker", "Git"})
    cv = make_cv(skills_canonical={"Python", "SQL"})
    value, ok, hits = skills_component(job, cv)
    assert ok is True
    assert value == 0.5
    assert hits == ["Python", "SQL"]


def test_skills_component_full_coverage():
    job = make_job(skills_canonical={"Python", "SQL"})
    cv = make_cv(skills_canonical={"Python", "SQL", "Docker"})
    value, ok, _hits = skills_component(job, cv)
    assert ok is True
    assert value == 1.0


# ── keywords_component ──────────────────────────────────────────────────


def test_keywords_component_no_signal_when_job_has_no_keywords():
    job = make_job(keyword_set=set())
    cv = make_cv(keyword_set={"laravel"})
    value, ok, hits = keywords_component(job, cv)
    assert (value, ok, hits) == (0.5, False, [])


def test_keywords_component_checks_both_keyword_set_and_text_tokens():
    job = make_job(keyword_set={"laravel", "vuejs"})
    cv = make_cv(keyword_set={"laravel"}, text_tokens={"vuejs", "docker"})
    value, ok, hits = keywords_component(job, cv)
    assert ok is True
    assert value == 1.0
    assert hits == ["laravel", "vuejs"]


# ── experience_zone_score / experience_component ────────────────────────


def test_experience_zone_equal():
    assert experience_zone_score(5, 5) == 1.0


def test_experience_zone_comfortably_over_is_full_credit():
    # job wants 3, cv has 6 -> ratio 2.0, exactly at the comfortable boundary
    assert experience_zone_score(6, 3) == 1.0


def test_experience_zone_severely_over_hits_floor():
    # job wants 2, cv has 8+ -> ratio >= 4.0
    assert experience_zone_score(8, 2) == 0.85


def test_experience_zone_tapers_between_comfortable_and_severe():
    # job wants 2, cv has 5 -> ratio 2.5, strictly between 2.0 and 4.0
    score = experience_zone_score(5, 2)
    assert 0.85 < score < 1.0


def test_experience_zone_shortfall_is_linear():
    # job wants 10, cv has 5 -> 50% shortfall
    assert experience_zone_score(5, 10) == 0.5


def test_experience_component_no_signal_when_neither_side_has_years():
    job = make_job(min_experience_years=None)
    cv = make_cv(experience_years=None)
    assert experience_component(job, cv) == (0.5, False)


def test_experience_component_no_signal_when_job_states_no_requirement():
    job = make_job(min_experience_years=None)
    cv = make_cv(experience_years=5)
    assert experience_component(job, cv) == (0.75, False)


def test_experience_component_no_signal_when_cv_years_missing():
    job = make_job(min_experience_years=3)
    cv = make_cv(experience_years=None)
    assert experience_component(job, cv) == (0.2, False)


def test_experience_component_real_comparison():
    job = make_job(min_experience_years=3)
    cv = make_cv(experience_years=3)
    value, ok = experience_component(job, cv)
    assert ok is True
    assert value == 1.0


# ── jobtype / category / location / salary / qualification ──────────────


def test_jobtype_component_match():
    job = make_job(jobtype="cdi")
    cv = make_cv(jobtype="cdi")
    assert jobtype_component(job, cv) == (1.0, True)


def test_jobtype_component_mismatch():
    job = make_job(jobtype="cdi")
    cv = make_cv(jobtype="freelance")
    assert jobtype_component(job, cv) == (0.0, True)


def test_jobtype_component_no_signal():
    job = make_job(jobtype="")
    cv = make_cv(jobtype="cdi")
    assert jobtype_component(job, cv) == (0.5, False)


def test_category_component_match():
    job = make_job(category="developpement web")
    cv = make_cv(category="developpement web")
    assert category_component(job, cv) == (1.0, True)


def test_location_component_substring_match():
    job = make_job(location="paris")
    cv = make_cv(location="paris 15e")
    assert location_component(job, cv) == (1.0, True)


def test_salary_component_within_budget():
    job = make_job(salary_max=50000)
    cv = make_cv(salary_expected_min=45000)
    assert salary_component(job, cv) == (1.0, True)


def test_salary_component_above_budget():
    job = make_job(salary_max=50000)
    cv = make_cv(salary_expected_min=60000)
    assert salary_component(job, cv) == (0.0, True)


def test_qualification_component_true():
    cv = make_cv(qualified=True)
    assert qualification_component(cv) == (1.0, True)


def test_qualification_component_none_is_no_signal():
    cv = make_cv(qualified=None)
    assert qualification_component(cv) == (0.5, False)


# ── compute_final_score : moyenne pondérée renormalisée ──────────────────


def test_final_score_renormalizes_over_missing_components():
    """Un job qui ne fournit AUCUN signal structuré à part skills doit voir
    son score déterminé uniquement par semantic+skills, renormalisés --
    pas dilué par des composantes neutres comptées à plein poids."""
    job = make_job(skills_canonical={"Python", "SQL"})
    cv = make_cv(skills_canonical={"Python", "SQL"})
    result = compute_final_score(job, cv, similarity=1.0, rerank_score=None)

    expected_weight_total = DEFAULT_WEIGHTS["semantic"] + DEFAULT_WEIGHTS["skills"]
    expected_final = (
        DEFAULT_WEIGHTS["semantic"] * 1.0 + DEFAULT_WEIGHTS["skills"] * 1.0
    ) / expected_weight_total
    assert result.score == round(expected_final * 100, 2)
    assert set(result.low_confidence_components) == {
        "keywords",
        "experience",
        "jobtype",
        "category",
        "location",
        "salary",
        "qualification",
    }


def test_final_score_falls_back_to_neutral_when_nothing_has_signal():
    job = make_job()
    cv = make_cv()
    result = compute_final_score(job, cv, similarity=0.0, rerank_score=None)
    # semantic always counts (weight_total > 0), so this isn't the 0.5
    # fully-neutral fallback -- just semantic alone at similarity 0.0.
    assert result.score == 0.0


def test_final_score_uses_rerank_score_over_raw_similarity():
    job = make_job()
    cv = make_cv()
    result = compute_final_score(job, cv, similarity=0.1, rerank_score=0.9)
    assert result.semantic == 0.9


def test_skill_coverage_caps_the_final_score():
    """Une similarité sémantique parfaite ne doit pas compenser une
    couverture de compétences quasi nulle -- même mécanisme que
    _SKILL_CAP_FLOOR chez AI Real-Time."""
    job = make_job(skills_canonical={"Python", "SQL", "Docker", "Kubernetes"})
    cv = make_cv(skills_canonical={"Python"})  # 1/4 coverage = 0.25
    result = compute_final_score(job, cv, similarity=1.0, rerank_score=None)

    cap = (SKILL_CAP_FLOOR + (1 - SKILL_CAP_FLOOR) * 0.25) * 100
    assert result.score <= round(cap, 2)


def test_skill_coverage_cap_does_not_hold_back_perfect_coverage():
    job = make_job(skills_canonical={"Python"})
    cv = make_cv(skills_canonical={"Python"})
    result = compute_final_score(job, cv, similarity=1.0, rerank_score=None)
    assert result.score == 100.0


def test_keywords_coverage_also_caps_the_final_score():
    job = make_job(keyword_set={"laravel", "vuejs", "mysql", "docker"})
    cv = make_cv(keyword_set={"laravel"})  # 1/4 coverage
    result = compute_final_score(job, cv, similarity=1.0, rerank_score=None)

    cap = (SKILL_CAP_FLOOR + (1 - SKILL_CAP_FLOOR) * 0.25) * 100
    assert result.score <= round(cap, 2)


def test_custom_weights_are_respected():
    job = make_job(skills_canonical={"Python"})
    cv = make_cv(skills_canonical={"Python"})
    custom = dict(DEFAULT_WEIGHTS)
    custom["skills"] = 0.0
    result = compute_final_score(job, cv, similarity=0.5, rerank_score=None, weights=custom)
    # With skills weighted at 0, only semantic counts -> final == semantic.
    assert result.score == 50.0
