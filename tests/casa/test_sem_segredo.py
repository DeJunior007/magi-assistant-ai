# ruff: noqa: F811 - fixtures importadas de outros módulos de teste
"""CA-Y49: um ciclo completo descobrir → nomear → parear (Samsung e Android TV) → 20 ações, com
drivers falsos, e nenhum log (JSON da casa em DEBUG + ``caplog`` de todas as bibliotecas) nem saída
da CLI contém token, código de pareamento, conteúdo de cert/chave nem texto digitado."""

from __future__ import annotations

import functools
import logging

from magi.casa import cli, pareamento
from magi.casa.driver import Cap, Capacidades
from magi.casa.falso import DriverFalso
from tests.casa.drivers.test_androidtv import RemotoFalso
from tests.casa.drivers.test_samsung import Keyring, fazer, tv_falsa  # noqa: F401 - fixture
from tests.casa.test_descoberta import sem_udp  # noqa: F401 - fixture
from tests.casa.test_pareamento import _descobridor

TOKEN = "tokSEGREDOsamsung4242"
CODIGO = "C0DE42"
CERT = b"-----BEGIN CERTIFICATE-----\nCERTSEGREDOconteudo\n-----END CERTIFICATE-----\n"
CHAVE = b"-----BEGIN PRIVATE KEY-----\nKEYSEGREDOconteudo\n-----END PRIVATE KEY-----\n"
TEXTO = "minha senha do wifi é hunter2"
SEGREDOS = (TOKEN, CODIGO, "CERTSEGREDO", "KEYSEGREDO", TEXTO, "hunter2")


class RemotoCodigo(RemotoFalso):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.codigos_certos = {CODIGO}


async def test_ciclo_completo_sem_segredo_no_log(tv_falsa, relogio, tmp_path, log_casa, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    tv_falsa.token_novo = TOKEN
    kr = Keyring()

    # descobrir + nomear
    assert await _sync(cli.descobrir, ["--segundos", "0.1"], descobridor=_descobridor()) == 0
    assert await _sync(cli.nomear, ["samsung:uuid:abc", "sala", "TV da sala", "--padrao"]) == 0
    assert await _sync(cli.nomear, ["10.0.0.52", "quarto", "TV do quarto"]) == 0

    # parear: Samsung pela WS falsa (token no 1º frame); Android TV com 1 código errado e 1 certo
    drv_samsung = fazer(tv_falsa, relogio, tmp_path, keyring=kr)
    codigos = iter(["ABCDEF", CODIGO])
    par = functools.partial(
        pareamento.parear,
        driver_samsung=drv_samsung,
        fabrica_atv=lambda c, k, h: RemotoCodigo(),
        gerar_cert=lambda nome: (CERT, CHAVE),
        prazo_s=5.0,
    )
    assert await _sync(cli.parear, ["sala"], pareador=par, ler_codigo=lambda p: next(codigos)) == 0
    assert await _sync(cli.parear, ["quarto"], pareador=par, ler_codigo=lambda p: next(codigos)) == 0
    assert kr.valores == {"casa.sala.samsung": TOKEN}

    # 20 ações pelo Executor (drivers falsos), com texto digitado no meio
    caps = Capacidades(caps=frozenset(Cap), entradas=("hdmi1", "hdmi2"), apps=("netflix",))
    falsos: dict[str, DriverFalso] = {}

    def fabrica(tv, ctx):
        return falsos.setdefault(tv.id, DriverFalso(caps, tv_id=tv.id, tv_nome=tv.nome))

    acoes = [
        ["sala", "power_on"],
        ["sala", "volume", "volume=+2"],
        ["sala", "volume", "volume=30"],
        ["sala", "mute"],
        ["sala", "unmute"],
        ["sala", "app", "app=netflix"],
        ["sala", "input", "input=hdmi2"],
        ["sala", "key", "key=ok"],
        ["sala", "text", f"texto={TEXTO}"],
        ["sala", "channel", "step=1"],
        ["quarto", "power_on"],
        ["quarto", "text", f"texto={TEXTO}"],
        ["quarto", "volume", "volume=-3"],
        ["quarto", "key", "key=home"],
        ["quarto", "app", "app=netflix"],
        ["quarto", "state"],
        ["quarto", "power_off"],
        ["sala", "state"],
        ["sala", "text", f"texto={TEXTO}"],
        ["sala", "power_off"],
    ]
    assert len(acoes) == 20
    for a in acoes:
        await _sync(cli.testar, a, fabrica_driver=fabrica, relogio=relogio, dormir=relogio.dormir)
    assert sum(len(d.de("text")) for d in falsos.values()) == 3
    await _sync(cli.estado, [])

    saida = capsys.readouterr()
    tudo = "\n".join(
        [log_casa.texto, caplog.text, saida.out, saida.err, *(r.getMessage() for r in caplog.records)]
    )
    for s in SEGREDOS:
        assert s not in tudo, s
    linhas = log_casa.linhas()
    assert sum(1 for x in linhas if x["evento"] == "acao") == 20
    assert any(x["evento"] == "pareamento" and x.get("ok") for x in linhas)


async def _sync(fn, *a, **kw):
    """Os subcomandos usam ``asyncio.run``; aqui rodam numa thread para não aninhar loops."""
    import asyncio

    return await asyncio.to_thread(fn, *a, **kw)
