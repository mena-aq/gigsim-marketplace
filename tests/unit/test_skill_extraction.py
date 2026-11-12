"""Unit tests for skill inference from job text (Kaggle feeds have no skills column)."""

from data.scripts.process import extract_skills


def test_extracts_relevant_skills_within_limit():
    skills = extract_skills(
        "Senior React and TypeScript developer",
        "Build a dashboard with Node.js and PostgreSQL.",
        "react typescript",
    )
    assert 2 <= len(skills) <= 3
    assert "React" in skills
    assert "TypeScript" in skills


def test_uses_search_keyword_hints():
    skills = extract_skills("Build a small website", "Small marketing site.", "wordpress php")
    assert "WordPress" in skills
    assert "PHP" in skills


def test_falls_back_to_category_skills():
    skills = extract_skills("Need help with a project", "Short description")
    assert 2 <= len(skills) <= 3
    assert skills == extract_skills("Need help with a project", "Short description")


def test_does_not_match_skill_inside_another_word():
    skills = extract_skills("Digital marketing audit", "Trust and reputation review")
    assert "Git" not in skills
    assert "Rust" not in skills
