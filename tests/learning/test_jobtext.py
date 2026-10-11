"""LI0.1: texto colado da vaga (spec §1, R1.5, CA-01)."""

from __future__ import annotations

import pytest

from magi.learning.interview import jobtext
from magi.learning.interview.contracts import JOB_ID_RE, JOB_MAX, JOB_MIN

FILLER = "We build payment APIs for small shops across Latin America and need help scaling them.\n"

# 6 textos colados (estilo LinkedIn, Gupy e e-mail; inventados, sem dados reais).
LINKEDIN = (
    "Senior Backend Engineer\r\nAcme Pay · São Paulo (Remote)\r\n\r\n\r\n\r\nAbout the job\r\n"
    "• 5+ years with Python\r\n• Experience with PostgreSQL\r\n• Kubernetes in production\r\n"
    "Show more\r\nApply now\r\n" + FILLER * 3
)
GUPY = (
    "Desenvolvedor(a) Full Stack Pleno\n\nRequisitos:\n– Experiência com React\n– Node.js\n"
    "○ Inglês avançado\nCandidatar-se\nVer mais\n" + FILLER * 3
)
EMAIL = (
    "Hi Pedro,\n\nWe have an opening for a Data Engineer.\n   * Spark and Airflow   \n"
    "   * SQL (advanced)\n\nBest,\nRecruiter\nSalvar\n" + FILLER * 3
)
BULLET_DOT = "Platform Engineer\n· Terraform\n· AWS\n· Go\nSave\n" + FILLER * 3
MIXED = "Staff Engineer\n\n\n\n\n• Mentoring\n  •   Architecture  \nAPPLY NOW\n" + FILLER * 3
PLAIN = "Backend Developer\n- Python\n- Django\n- Celery\n" + FILLER * 3
SAMPLES = [LINKEDIN, GUPY, EMAIL, BULLET_DOT, MIXED, PLAIN]


@pytest.mark.parametrize("raw", SAMPLES)
def test_ca01_normalize_keeps_bullets(raw: str) -> None:
    out = jobtext.normalize(raw)
    lines = [x.strip() for x in raw.replace("\r", "").split("\n")]
    bullets = sum(1 for x in lines if x[:1] in "•·–*○-" and x)
    assert sum(1 for x in out.split("\n") if x.startswith("- ")) == bullets
    assert "\r" not in out
    assert "\n\n\n\n" not in out
    for noise in ("Apply now", "Show more", "Candidatar-se", "Ver mais", "Salvar", "APPLY NOW"):
        assert noise not in out.split("\n")
    assert all(line == line.strip() for line in out.split("\n"))
    assert jobtext.check(raw).ok


def test_normalize_specifics() -> None:
    out = jobtext.normalize(LINKEDIN)
    assert out.startswith("Senior Backend Engineer\nAcme Pay")
    assert "- 5+ years with Python" in out
    assert "\n\nAbout the job" in out  # 4 linhas vazias → 1
    assert "\n\n" in jobtext.normalize("a\n\nb")  # 1 vazia fica


def test_job_id_stable() -> None:
    a = jobtext.job_id(jobtext.normalize(LINKEDIN))
    b = jobtext.job_id(jobtext.normalize(LINKEDIN.replace("\r\n", "\n") + "\n\n"))
    assert a == b and JOB_ID_RE.match(a)
    assert a != jobtext.job_id(jobtext.normalize(GUPY))


def test_check_refuses_short_and_empty() -> None:
    for raw in (None, "", "   \n ", "x" * (JOB_MIN - 1)):
        c = jobtext.check(raw)
        assert not c.ok and c.line == jobtext.TOO_SHORT


def test_check_trims_long_at_newline() -> None:
    raw = ("line of a very long job post " * 3 + "end\n") * 400
    c = jobtext.check(raw)
    assert c.ok and c.trimmed and c.line == jobtext.TRIMMED
    assert len(c.text) <= JOB_MAX
    assert raw.replace("\n", "").startswith(c.text.replace("\n", ""))
    assert c.text.endswith("end")  # cortou numa quebra de linha
    assert jobtext.normalize(raw) == c.text


def test_long_paste() -> None:
    assert jobtext.is_long_paste("a\nb")
    assert jobtext.is_long_paste("x" * 601)
    assert not jobtext.is_long_paste("x" * 600)
    assert not jobtext.is_long_paste("")
