from __future__ import annotations
import pytest

@pytest.fixture
def profile():
    return {"name": "Alex Example", "degree": "Computer Science", "year": "third-year", "skills": ["Python", "SQL", "machine learning"]}
