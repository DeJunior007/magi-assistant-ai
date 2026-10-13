"""CA-Y9: ``/saude`` sem token, sem dado pessoal (varredura das chaves), 503 com banco falso fora."""

from __future__ import annotations

from datetime import timedelta

import pytest

from ayanami.config import Segredos

PROIBIDAS = {"nome", "nomes", "tv", "tvs", "texto", "email", "e_mail", "token", "hash", "prefixo",
             "dsn", "senha", "preferencias", "escopos", "resumo", "alvo"}


def _chaves(obj, saida=None):
    saida = set() if saida is None else saida
    if isinstance(obj, dict):
        for k, v in obj.items():
            saida.add(k)
            _chaves(v, saida)
    elif isinstance(obj, list):
        for v in obj:
            _chaves(v, saida)
    return saida


async def test_banco_fora_da_503(fazer_app, db_fora, cliente):
    app = fazer_app(db_fora, segredos=Segredos({}, ("OPENAI_API_KEY",)))
    async with cliente(app) as c:
        r = await c.get("/saude")
    assert r.status_code == 503
    assert r.json() == {"ok": False, "banco": "falha", "faltando": ["OPENAI_API_KEY"]}


@pytest.mark.pg
async def test_saude_sem_token_e_sem_dado_pessoal(fazer_app, db, cliente, novo_token, relogio):
    pc = novo_token("pc-do-pedro", "pc")
    novo_token("casa-sala", "casa")
    agora = relogio.agora()
    with db.connection() as conn:
        visto = "UPDATE dispositivos SET visto = %s WHERE nome = %s"
        conn.execute(visto, (agora - timedelta(seconds=10), "pc-do-pedro"))
        conn.execute(visto, (agora - timedelta(seconds=40), "casa-sala"))
        conn.execute("INSERT INTO workers_batimento VALUES ('rapida', 'node2', %s)", (agora,))
        conn.execute("INSERT INTO backups (origem, data, bytes, sha256, manifesto, recebido)"
                     " VALUES ('pc', '2026-01-01', 10, 'x', '{\"tv\": \"TV da sala\"}', %s)", (agora,))
    app = fazer_app(db, segredos=Segredos({"POSTGRES_PASSWORD": "segredo-falso"}, ()))
    async with cliente(app) as c:
        r = await c.get("/saude")
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True and j["banco"] == "ok" and j["faltando"] == []
    assert j["fila"]["rapida"] == {"todo": 0, "doing": 0, "failed_24h": 0}
    assert set(j["fila"]) >= {"agendada", "lenta"}
    assert j["workers"] == {"rapida": "2026-01-01T12:00:00Z"}
    assert j["ultimo_backup"] == {"pc": "2026-01-01T12:00:00Z", "ayanami": None, "restic": None}
    assert j["online"] == {"pc": True, "casa": False, "celulares": 0}
    assert not (_chaves(j) & PROIBIDAS)
    for proibido in ("pc-do-pedro", "casa-sala", "TV da sala", "ayn_", pc[12:], "segredo-falso"):
        assert proibido not in r.text


@pytest.mark.pg
async def test_celular_em_uso_conta_online(fazer_app, db, cliente, novo_token):
    app = fazer_app(db)
    cel = novo_token("cel", "celular")
    async with cliente(app, cel) as c:
        await c.get("/v1/feed")
    async with cliente(app) as c:
        j = (await c.get("/saude")).json()
    assert j["online"]["celulares"] == 1 and j["faltando"] == []
