"""Redator de segredos (P0.3; ayanami-plataforma spec §5, DSP6; CA-P10).

Todos os segredos aqui são falsos e fixos; os prefixos são montados por concatenação para não
disparar scanners de segredo no repo público.
"""

from __future__ import annotations

import random
import string
import time

import pytest

from ayanami.redator import LIMITE, MARCA_TRUNCADO, NOMES_DAS_REGRAS, ORIGENS, envelope, redigir

_GH = "gh" + "p_"
_PK_INI = "-----BEGIN "
_PK_FIM = "-----END "

# (regra, texto completo, trecho secreto que não pode sobrar)
AMOSTRAS: list[tuple[str, str, str]] = [
    ("github_pat", f"git remote set-url origin {_GH}{'Ab1Cd2Ef3' * 4}", f"{_GH}{'Ab1Cd2Ef3' * 4}"),
    ("github_pat", "GH_TOKEN " + "gh" + "o_" + "FalsoExemplo" * 3 + " ok", "FalsoExemploFalso"),
    ("github_pat", "usando " + "github_" + "pat_11FALSO0000_exemplo_falso_abc", "11FALSO0000_exemplo"),
    ("aws_chave", "aws configure set key " + "AK" + "IAFALSOEXEMPLO1234", "IAFALSOEXEMPLO1234"),
    (
        "jwt",
        "cookie sessao=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJmYWxzbyJ9.ZmFsc28tYXNzaW5hdHVyYQ; Path=/",
        "ZmFsc28tYXNzaW5hdHVyYQ",
    ),
    (
        "chave_privada",
        f"antes\n{_PK_INI}RSA PRIVATE KEY-----\nMIIEfalsoExemplo\nAAAAfalso==\n"
        f"{_PK_FIM}RSA PRIVATE KEY-----\ndepois",
        "MIIEfalsoExemplo",
    ),
    (
        "chave_privada",
        f"{_PK_INI}OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEfalso\n(cortado no log",
        "b3BlbnNzaC1rZXktdjEfalso",
    ),
    ("laravel_app_key", "APP_KEY=base64:ZmFsc29fZXhlbXBsb19kZV9jaGF2ZV8zMmI=", "ZmFsc29fZXhlbXBsb19kZV9j"),
    (
        "url_com_senha",
        "DATABASE_URL=postgres://ayanami:senha-falsa-42@db.exemplo.invalid:5432/app",
        "senha-falsa-42",
    ),
    ("url_com_senha", "clonando https://pedro:x-falso-123@git.exemplo.invalid/r.git", "x-falso-123"),
    ("ayanami_token", "MCP com " + "ayn_" + "falso_exemplo_0123456789abc", "falso_exemplo_0123456789"),
    ("bearer", "curl -H 'Authorization: Bearer abcdefgh12345678falso' x", "abcdefgh12345678falso"),
    ("bearer", '{"Authorization": "Bearer xyzFalso12345678.zz"}', "xyzFalso12345678"),
    ("atribuicao_segredo", "conectando com password=hunter2falso", "hunter2falso"),
    ("atribuicao_segredo", "secret: s3gr3d0-falso", "s3gr3d0-falso"),
    ("atribuicao_segredo", 'api_key = "chave-falsa-123456"', "chave-falsa-123456"),
    ("atribuicao_segredo", "export TOKEN=tok3nFalsoExemplo", "tok3nFalsoExemplo"),
    ("atribuicao_segredo", "passwd:'abcdef-falso'", "abcdef-falso"),
    ("stripe", "cobranca com " + "sk_" + "live_" + "FalsoExemplo1234567890", "FalsoExemplo1234567890"),
    ("slack", "SLACK=" + "xox" + "b-1234567890-falso-exemplo", "1234567890-falso-exemplo"),
    ("slack", "webhook " + "xox" + "p-0987654321-outro-falso", "0987654321-outro-falso"),
]

INOCENTES = [
    "===== 42 passed, 3 skipped in 1.23s =====",
    "tests/ayanami/test_fila.py::test_def_tem_todos PASSED [ 10%]",
    "commit c04879a1b2c3d4e5f60718293a4b5c6d7e8f9012 (HEAD -> main)",
    "pedido 3f2b8c1e-9a4d-4e7b-8c2f-1d5e6a7b8c9d concluído",
    "token_count=5",
    "usage: input_tokens=1234 output_tokens=567",
    "GET https://exemplo.invalid/v1/saude 200 OK",
    "Authorization header ausente (401)",
    "ERROR: secret not found; APP_KEY ausente no .env",
    "ver https://exemplo.invalid/u/pull/12 (" + _GH + "curto)",
]


def test_amostras_cobrem_todas_as_regras() -> None:
    assert len(AMOSTRAS) >= 20
    assert {r for r, _, _ in AMOSTRAS} == set(NOMES_DAS_REGRAS)


@pytest.mark.parametrize(("regra", "texto", "segredo"), AMOSTRAS)
def test_amostra_redigida(regra: str, texto: str, segredo: str) -> None:
    r = redigir(texto)
    assert segredo not in r.texto
    assert f"⟦redigido:{regra}⟧" in r.texto
    assert r.contagem.get(regra, 0) >= 1


@pytest.mark.parametrize("texto", INOCENTES)
def test_inocente_intacto(texto: str) -> None:
    r = redigir(texto)
    assert r.texto == texto
    assert r.contagem == {}
    assert r.total == 0


def test_prefixo_legivel_preservado() -> None:
    assert redigir("Authorization: Bearer abcdefgh12345678falso").texto == (
        "Authorization: Bearer ⟦redigido:bearer⟧"
    )
    assert redigir("postgres://u:senha-falsa@h.exemplo.invalid/db").texto == (
        "postgres://⟦redigido:url_com_senha⟧@h.exemplo.invalid/db"
    )


def test_sem_redigir_duas_vezes() -> None:
    texto = "token=" + "ayn_" + "falso_exemplo_0123456789abc"
    r = redigir(texto)
    assert r.texto == "token=⟦redigido:ayanami_token⟧"
    assert r.contagem == {"ayanami_token": 1}
    assert redigir(r.texto).contagem == {}


def test_contagem_por_regra() -> None:
    texto = "\n".join(t for regra, t, _ in AMOSTRAS if regra == "atribuicao_segredo")
    assert redigir(texto).contagem == {"atribuicao_segredo": 5}


@pytest.mark.parametrize("origem", sorted(ORIGENS))
def test_envelope_nao_confiavel(origem: str) -> None:
    env = envelope(origem, "log com password=hunter2falso")
    assert env == {
        "nao_confiavel": True,
        "origem": origem,
        "texto": "log com password=⟦redigido:atribuicao_segredo⟧",
    }


def test_envelope_origem_desconhecida() -> None:
    with pytest.raises(ValueError, match="origem desconhecida"):
        envelope("telepatia", "x")


def test_entrada_grande_truncada_antes() -> None:
    texto = "a" * (LIMITE + 10) + " password=hunter2falso"
    r = redigir(texto)
    assert r.texto == "a" * LIMITE + MARCA_TRUNCADO
    assert r.contagem == {}


def test_200kb_de_lixo_rapido() -> None:
    rng = random.Random(10)
    alfabeto = string.printable + "⟦⟧é"
    lixo = "".join(rng.choice(alfabeto) for _ in range(200_000))
    lixo += "".join(rng.choice(["://", "eyJ", "-----BEGIN ", "token=", "a:b@", "ayn_"]) for _ in range(2_000))
    t0 = time.perf_counter()
    redigir(lixo)
    assert time.perf_counter() - t0 < 0.2
