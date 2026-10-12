"""Mensagens do elo: CA-Y1, CA-Y2, ids, schema determinístico e pureza (sem rede)."""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from magi.elo import ids, schema
from magi.elo.mensagens import (
    MAX_TEXTO_BYTES,
    Acao,
    AcaoOk,
    AcaoPedido,
    AcaoResultado,
    Ack,
    AppInfo,
    Bate,
    CardElo,
    Confirma,
    EloError,
    Envelope,
    Erro,
    Estado,
    EstadoTv,
    Evento,
    EventoTipo,
    Ola,
    ResumoNuvem,
    Tipo,
    TipoDispositivo,
    Turno,
    TurnoFim,
    TurnoNuvem,
    TvInfo,
    decode,
    encode,
    responder,
)

RAIZ = Path(__file__).resolve().parents[2]
TS = datetime(2026, 10, 12, 21, 4, 5, 123_000, tzinfo=UTC)


def _id(n: int) -> str:
    return ids.novo_id(agora_ms=lambda: 1_760_000_000_000 + n, rng=lambda k: bytes([n % 256]) * k)


TURNO = _id(1)

CORPOS = {
    Tipo.OLA: Ola(
        tipo=TipoDispositivo.CASA,
        versao="0.9.0+ecf2c08",
        caps=("acao", "estado"),
        retomar_desde=_id(2),
        tvs=(TvInfo(id="sala", nome="TV da sala", driver="samsung", apelidos=("sala",), padrao=True),),
        apps=(AppInfo(id="netflix", nome="Netflix", apelidos=("netflix",)),),
    ),
    Tipo.BATE: Bate(seq=3, custos_mes_usd=1.25),
    Tipo.TURNO: Turno(turno=TURNO, texto="que horas são? ação ✨", dispositivo="celular-pedro"),
    Tipo.TURNO_FIM: TurnoFim(
        turno=TURNO,
        ok=True,
        texto="São nove horas, querido. 🌙",
        fala="São nove.",
        cards=(CardElo(titulo="Fonte", url="https://ex.com", nivel="link"),),
        expressao="smug",
        audio=True,
    ),
    Tipo.ACAO: Acao(
        pedido=AcaoPedido(
            intent="tv.volume",
            slots=(("volume", "30"), ("tv", "sala")),
            texto="volume 30 na tv",
            confirmed=True,
            args={"force": True, "n": 2, "x": 0.5, "s": "á"},
        ),
        origem="pwa",
        prazo_ms=10_000,
    ),
    Tipo.ACAO_OK: AcaoOk(
        resultado=AcaoResultado(
            ok=False, fala="Não deu.", motivo="tempo_esgotado", dados={"tv": "sala", "lista": [1, 2]}
        )
    ),
    Tipo.ESTADO: Estado(
        tvs=(
            EstadoTv(
                id="sala",
                nome="TV da sala",
                driver="androidtv",
                online=True,
                ligada=True,
                volume=20,
                visto=TS,
            ),
            EstadoTv(id="quarto", nome="Quarto", driver="roku", online=False),
        )
    ),
    Tipo.EVENTO: Evento(seq=42, tipo=EventoTipo.TAREFA_PRONTA, titulo="Pesquisa pronta", ref="tarefa:abc"),
    Tipo.CONFIRMA: Confirma(
        pedido=_id(5), descricao="desligar a TV da sala", expira_em=TS + timedelta(seconds=120)
    ),
    Tipo.RESUMO_NUVEM: ResumoNuvem(
        turnos=(
            TurnoNuvem(
                uid="0f6c2f7e-0000-4000-8000-000000000001",
                ts=TS,
                dispositivo="celular-pedro",
                texto_usuario="oi",
                texto_resposta="olá, querido 💜",
                ferramentas=("web_search",),
            ),
        ),
        restam=3,
    ),
    Tipo.ACK: Ack(ids=("0f6c2f7e-0000-4000-8000-000000000001",)),
    Tipo.ERRO: Erro(codigo="offline", msg="a casa está fora"),
}


def _env(t: Tipo) -> Envelope:
    return Envelope(t=t, corpo=CORPOS[t], de="ayanami", para="pc", id=_id(10), ts=TS, resp=None)


def _cru(**troca: object) -> dict:
    d = json.loads(encode(_env(Tipo.ACAO)))
    d.update(troca)
    return d


# --------------------------------------------------------------------------------------------- ids


def test_ulid_ida_e_volta_binaria() -> None:
    u = ids.novo_id(agora_ms=lambda: 1_760_000_000_123, rng=lambda k: bytes(range(k)))
    assert ids.valido(u) and len(u) == 26
    assert ids.de_bytes(ids.para_bytes(u)) == u
    assert ids.ms_de(u) == 1_760_000_000_123
    assert len(ids.para_bytes(u)) == 16
    assert ids.valido(ids.novo_id())


@pytest.mark.parametrize(
    "ruim",
    [
        "",
        "x" * 26,
        "01JA2Z7Q8M4V0K3N5R6S7T8W9",
        "81JA2Z7Q8M4V0K3N5R6S7T8W9X",
        "01ja2z7q8m4v0k3n5r6s7t8w9x",
        5,
    ],
)
def test_ulid_invalido(ruim: object) -> None:
    assert not ids.valido(ruim)


def test_ulid_ordena_por_tempo() -> None:
    a = ids.novo_id(agora_ms=lambda: 1000, rng=lambda k: b"\xff" * k)
    b = ids.novo_id(agora_ms=lambda: 1001, rng=lambda k: b"\x00" * k)
    assert a < b


# --------------------------------------------------------------------------------------------- CA-Y1


def test_ca_y1_cobre_os_12_tipos() -> None:
    assert set(CORPOS) == set(Tipo)


@pytest.mark.parametrize("t", list(Tipo))
def test_ca_y1_ida_e_volta(t: Tipo) -> None:
    env = _env(t)
    s = encode(env)
    assert decode(s) == env
    assert decode(s.encode()) == env
    assert '"ts":"2026-10-12T21:04:05.123Z"' in s


def test_ca_y1_acentos_sem_escape() -> None:
    s = encode(_env(Tipo.TURNO))
    assert "ação ✨" in s


def test_ts_normaliza_para_utc_em_ms() -> None:
    br = timezone(timedelta(hours=-3))
    env = Envelope(
        t=Tipo.BATE,
        corpo=Bate(seq=0),
        de="pc",
        para="ayanami",
        ts=datetime(2026, 10, 12, 18, 4, 5, 123_456, tzinfo=br),
    )
    assert env.ts == TS
    assert decode(encode(env)) == env


def test_responder() -> None:
    pedido = _env(Tipo.ACAO)
    r = responder(pedido, Tipo.ACAO_OK, CORPOS[Tipo.ACAO_OK], de="casa")
    assert (r.para, r.resp, r.de) == ("ayanami", pedido.id, "casa")
    assert pedido.pede_resposta and not r.pede_resposta


# --------------------------------------------------------------------------------------------- CA-Y2


def _codigo(raw: str | bytes) -> str:
    with pytest.raises(EloError) as e:
        decode(raw)
    return e.value.codigo


@pytest.mark.parametrize(
    ("troca", "codigo"),
    [
        ({"v": 2}, "versao"),
        ({"v": True}, "versao"),
        ({"t": "xyz"}, "tipo"),
        ({"id": "nao-e-ulid"}, "campo"),
        ({"ts": "2026-10-12T21:04:05.123"}, "campo"),
        ({"ts": "ontem"}, "campo"),
        ({"de": "Pedro PC"}, "nome"),
        ({"para": "-x"}, "nome"),
        ({"corpo": {"origem": "pwa"}}, "campo"),
        ({"corpo": {"pedido": {"intent": "tv.mute"}, "origem": "pwa", "prazo_ms": 100}}, "campo"),
        ({"corpo": {"pedido": {"intent": 3}, "origem": "pwa"}}, "campo"),
        ({"resp": "zzz"}, "campo"),
    ],
)
def test_ca_y2_reprova(troca: dict, codigo: str) -> None:
    assert _codigo(json.dumps(_cru(**troca))) == codigo


def test_ca_y2_json_e_tamanho() -> None:
    assert _codigo("{nao json") == "json"
    assert _codigo("[1]") == "json"
    grande = _cru(corpo={"pedido": {"intent": "x", "texto": "a" * MAX_TEXTO_BYTES}, "origem": "pwa"})
    assert _codigo(json.dumps(grande)) == "tamanho"


def test_ca_y2_aceita_campo_extra() -> None:
    d = _cru(novo_no_envelope=1)
    d["corpo"]["campo_futuro"] = {"a": 1}
    d["corpo"]["pedido"]["outro"] = True
    assert decode(json.dumps(d)) == _env(Tipo.ACAO)


@pytest.mark.parametrize(
    ("corpo", "codigo"),
    [
        ({"turno": TURNO, "texto": "a" * 4001}, "tamanho"),
        ({"turno": TURNO, "texto": "oi", "audio": True}, "campo"),
        ({"turno": "x"}, "campo"),
    ],
)
def test_limites_do_turno(corpo: dict, codigo: str) -> None:
    assert _codigo(json.dumps(_cru(t="turno", corpo=corpo))) == codigo


def test_limites_diversos() -> None:
    assert (
        _codigo(json.dumps(_cru(t="evento", corpo={"seq": 1, "tipo": "monitor", "titulo": "a" * 81})))
        == "tamanho"
    )
    assert _codigo(json.dumps(_cru(t="evento", corpo={"seq": 1, "tipo": "xyz", "titulo": "a"}))) == "campo"
    assert _codigo(json.dumps(_cru(t="erro", corpo={"codigo": "x", "msg": "a" * 201}))) == "tamanho"
    assert _codigo(json.dumps(_cru(t="resumo_nuvem", corpo={"turnos": []}))) == "campo"
    tv = {"id": "a", "nome": "a", "driver": "roku", "online": True}
    assert _codigo(json.dumps(_cru(t="estado", corpo={"tvs": [tv] * 17}))) == "tamanho"
    assert _codigo(json.dumps(_cru(t="estado", corpo={"tvs": [{**tv, "volume": 101}]}))) == "campo"
    assert _codigo(json.dumps(_cru(t="bate", corpo={"seq": -1}))) == "campo"
    assert _codigo(json.dumps(_cru(t="bate", corpo={"seq": True}))) == "campo"
    dados = {"resultado": {"ok": True, "dados": {"x": "a" * 5000}}}
    assert _codigo(json.dumps(_cru(t="acao_ok", corpo=dados))) == "tamanho"


def test_envelope_reprova_na_construcao() -> None:
    with pytest.raises(EloError) as e:
        Envelope(t=Tipo.ACAO, corpo=Bate(seq=1), de="pc", para="casa")
    assert e.value.codigo == "campo"
    with pytest.raises(EloError) as e:
        Envelope(t=Tipo.BATE, corpo=Bate(seq=1), de="pc", para="casa", ts=datetime(2026, 1, 1))  # noqa: DTZ001
    assert e.value.codigo == "campo"
    with pytest.raises(EloError) as e:
        encode(Envelope(t=Tipo.ACK, corpo=Ack(ids=("a" * 1000,) * 70), de="pc", para="casa"))
    assert e.value.codigo == "tamanho"


# ---------------------------------------------------------------------------- schema e pureza


def test_schema_deterministico_e_igual_ao_arquivo() -> None:
    assert schema.texto() == schema.texto()
    arquivo = RAIZ / "ayanami" / "app" / "elo.schema.json"
    assert arquivo.read_text(encoding="utf-8") == schema.texto(), "rode: python -m magi.elo.schema > " + str(
        arquivo
    )
    s = json.loads(schema.texto())
    assert set(s["properties"]["t"]["enum"]) == {t.value for t in Tipo}
    assert len(s["allOf"]) == 12


REDE = {
    "socket",
    "ssl",
    "http",
    "urllib",
    "asyncio",
    "aiohttp",
    "httpx",
    "requests",
    "websockets",
    "selectors",
}


@pytest.mark.parametrize("nome", ["ids", "mensagens", "quadros", "converte", "receptor", "schema"])
def test_sem_import_de_rede(nome: str) -> None:
    arvore = ast.parse((RAIZ / "magi" / "elo" / f"{nome}.py").read_text(encoding="utf-8"))
    modulos: set[str] = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            modulos |= {a.name.split(".")[0] for a in no.names}
        elif isinstance(no, ast.ImportFrom) and no.module:
            modulos.add(no.module.split(".")[0])
    assert not modulos & REDE
