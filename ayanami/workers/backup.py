"""Backups restic na Ayanami (dono: Y4.2; spec §7.2, §7.3, design §9; corpos chamados por
``ayanami.fila``).

Tudo que vai para fora do processo passa por um **executor injetado** (``deps.extras["executor"]``,
``Comando -> Resultado``; padrão :func:`executar`, ``subprocess`` sem shell) e, antes dele, por
:func:`checar_comando` — lista branca de programas e subcomandos:

- ``restic`` só ``init``/``backup``/``forget``/``check``/``restore``; ``forget`` sempre com
  ``--group-by host,tags``, ``--tag`` e os três ``--keep-*`` (D15a, [DS7]);
- ``docker`` só ``run``/``cp``/``exec``/``stop``. ``run``/``cp``/``stop`` só com o nome fixo
  ``ayanami-restore-teste`` (``run`` com ``--rm`` e ``--network none``, sem porta nem volume);
  ``exec`` só nele ou, para o dump da Ayanami, ``pg_dump`` no ``ayanami-pg`` (a imagem não traz
  cliente do Postgres; Sobras da Y1.1);
- ``tar --zstd -xf … -C …`` (extração do restore de teste).

Jobs (§4.2; ``lock="restic"``): :func:`restic` (sobe ``/dados/entrada/pc/<data>``),
:func:`dump_ayanami`, :func:`enviar` (dump da Ayanami + ``/opt-config``, nunca o ``.env``; também
reenvia o que do PC ficou sem snapshot), :func:`reter`, :func:`verificar` e :func:`restore_teste`
(``restic restore latest --tag pc`` → contêiner descartável sem rede → ``pg_restore`` → contagens
contra o manifesto, tolerância 0 → ``restore_testes``; vermelho → ``evento backup_falhou`` e
Telegram; verde também avisa no Telegram). ``[backup] ligado = false`` → os jobs só saem.

Segredos de ``deps.extras["segredos"]`` (padrão :func:`ayanami.config.ler_segredos`); Telegram de
``deps.extras["telegram"]`` (padrão :func:`ayanami.telegram.de_segredos`). Nunca logar ``env``.

``ayanami backup iniciar`` (:func:`cli`) roda ``restic init`` uma vez; repositório já existente → 0.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Final
from uuid import uuid4
from zoneinfo import ZoneInfo

from procrastinate import JobContext

from ayanami.deps import DADOS_PADRAO, Deps

log = logging.getLogger("ayanami.workers.backup")

FUSO: Final = ZoneInfo("America/Sao_Paulo")
HOST: Final = "ayanami"
RESTORE: Final = "ayanami-restore-teste"
IMAGEM_RESTORE: Final = "pgvector/pgvector:pg16"
PG_AYANAMI: Final = "ayanami-pg"
OPT_CONFIG: Final = Path("/opt-config")
NOME_PC: Final = "magi-{data}.tar.zst"
MANIFESTO: Final = "manifesto.json"
DUMP_AYANAMI: Final = "ayanami.dump"
DUMP_PC: Final = "magi-pg.dump"
BASE_PC: Final = "magi"
DUMP_NO_CONTEINER: Final = "/tmp/magi-pg.dump"
KEEP: Final = ("--keep-daily", "7", "--keep-weekly", "4", "--keep-monthly", "6")
SEGREDOS_BACKUP: Final = ("B2_ACCOUNT_ID", "B2_ACCOUNT_KEY", "B2_BUCKET", "RESTIC_PASSWORD")
TABELAS_AYANAMI: Final = ("dispositivos", "eventos", "tarefas", "nuvem_turnos", "news_items", "backups")
ESPERA_PRONTO_S: Final = 2.0
TENTATIVAS_PRONTO: Final = 60

_SNAPSHOT_SALVO = re.compile(r"snapshot ([0-9a-f]{8,64}) saved")
_SNAPSHOT_RESTAURADO = re.compile(r"[Ss]napshot ([0-9a-f]{8,64})")
_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --------------------------------------------------------------------------- executor


@dataclass(frozen=True)
class Comando:
    argv: tuple[str, ...]
    env: Mapping[str, str] = field(default_factory=dict, repr=False)  # por cima do os.environ
    saida: Path | None = None  # stdout direto para este arquivo
    prazo_s: float | None = None


@dataclass(frozen=True)
class Resultado:
    codigo: int
    saida: str = ""
    erro: str = ""


Executor = Callable[[Comando], Resultado]


def executar(cmd: Comando) -> Resultado:
    """Executor real (sem shell)."""
    env = {**os.environ, **cmd.env}
    if cmd.saida is not None:
        with open(cmd.saida, "wb") as fh:
            p = subprocess.run(
                list(cmd.argv), env=env, stdout=fh, stderr=subprocess.PIPE, timeout=cmd.prazo_s, check=False
            )
        return Resultado(p.returncode, "", p.stderr.decode("utf-8", "replace"))
    p = subprocess.run(list(cmd.argv), env=env, capture_output=True, timeout=cmd.prazo_s, check=False)
    return Resultado(p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace"))


class ComandoProibido(RuntimeError):
    pass


class ErroBackup(RuntimeError):
    pass


class ErroComando(ErroBackup):
    def __init__(self, cmd: Comando, r: Resultado) -> None:
        self.codigo = r.codigo
        super().__init__(f"{' '.join(cmd.argv[:2])} saiu {r.codigo}: {r.erro.strip()[-300:]}")


def _valor_de(a: Sequence[str], opcao: str) -> str | None:
    if opcao not in a:
        return None
    i = a.index(opcao)
    return a[i + 1] if i + 1 < len(a) else None


def _proibido(msg: str) -> None:
    raise ComandoProibido(msg)


def checar_comando(cmd: Comando) -> None:
    """Lista branca da §7.2/§7.3; fora dela → :class:`ComandoProibido` (o comando não roda)."""
    a = tuple(cmd.argv)
    if len(a) < 2:
        _proibido("comando vazio")
    prog, sub = a[0], a[1]
    if prog == "restic":
        if sub not in ("init", "backup", "forget", "check", "restore"):
            _proibido(f"restic {sub}")
        if sub == "forget":
            if _valor_de(a, "--group-by") != "host,tags" or _valor_de(a, "--tag") is None:
                _proibido("restic forget sem --group-by host,tags/--tag")
            for k in KEEP[::2]:
                if _valor_de(a, k) is None:
                    _proibido(f"restic forget sem {k}")
        return
    if prog == "docker":
        if sub not in ("run", "cp", "exec", "stop"):
            _proibido(f"docker {sub}")
        if sub == "run":
            if (
                _valor_de(a, "--name") != RESTORE
                or _valor_de(a, "--network") != "none"
                or "--rm" not in a
                or a[-1] != IMAGEM_RESTORE
            ):
                _proibido("docker run fora do contêiner descartável")
            if any(
                x in ("-p", "--publish", "-P", "-v", "--volume", "--mount", "--privileged")
                or x.startswith(("--publish=", "--volume=", "--mount=", "--network="))
                for x in a
            ):
                _proibido("docker run com porta/volume")
        elif sub == "stop":
            if a[2:] != (RESTORE,):
                _proibido("docker stop fora do contêiner descartável")
        elif sub == "cp":
            if len(a) != 4 or not a[3].startswith(RESTORE + ":"):
                _proibido("docker cp fora do contêiner descartável")
        else:  # exec
            if len(a) < 4:
                _proibido("docker exec incompleto")
            alvo, programa, resto = a[2], a[3], a[4:]
            if alvo == RESTORE:
                if programa not in ("pg_isready", "pg_restore", "psql"):
                    _proibido(f"docker exec {programa}")
                ok = {
                    "pg_isready": {"-h", "-U"},
                    "pg_restore": {"--no-owner", "-U", "-d", "--create"},
                    "psql": {"-U", "-d", "-Atc"},
                }[programa]
                if any(x.startswith("-") and x not in ok for x in resto):
                    _proibido(f"docker exec {programa} com opção fora da lista")
                if programa == "psql" and not (_valor_de(a, "-Atc") or "").startswith(
                    "SELECT count(*) FROM "
                ):
                    _proibido("psql só com SELECT count(*)")
            elif alvo == PG_AYANAMI:
                if programa != "pg_dump" or any(
                    x.startswith("-") and x not in ("-Fc", "-U", "--version") for x in resto
                ):
                    _proibido("no ayanami-pg só pg_dump")
            else:
                _proibido(f"docker exec em {alvo}")
        return
    if prog == "tar":
        if a[1:3] != ("--zstd", "-xf") or len(a) != 6 or a[4] != "-C":
            _proibido("tar só para extrair")
        return
    _proibido(f"programa fora da lista: {prog}")


def _executor(deps: Deps) -> Executor:
    return deps.extras.get("executor") or executar


async def _rodar(deps: Deps, cmd: Comando, *, checar_codigo: bool = True) -> Resultado:
    checar_comando(cmd)
    r = await asyncio.to_thread(_executor(deps), cmd)
    if checar_codigo and r.codigo != 0:
        raise ErroComando(cmd, r)
    return r


# --------------------------------------------------------------------------- caminhos e ambiente


def data_valida(texto: Any) -> date:
    if not isinstance(texto, str) or not _DATA.match(texto):
        raise ValueError("data no formato AAAA-MM-DD")
    return date.fromisoformat(texto)


def pasta_pc(dados: Path, data: date | str) -> Path:
    return dados / "entrada" / "pc" / str(data)


def arquivo_pc(dados: Path, data: date | str) -> Path:
    return pasta_pc(dados, data) / NOME_PC.format(data=data)


def pasta_ayanami(dados: Path, data: date | str) -> Path:
    return dados / "entrada" / "ayanami" / str(data)


def _data_do(timestamp: int | float) -> date:
    return datetime.fromtimestamp(timestamp, FUSO).date()


def _segredos(deps: Deps) -> Any:
    s = deps.extras.get("segredos")
    if s is None:
        from ayanami.config import ler_segredos

        s = ler_segredos(deps.cfg)
        deps.extras["segredos"] = s
    return s


def ambiente_restic(segredos: Any, dados: Path) -> dict[str, str]:
    """Ambiente do ``restic`` (§7.2). Faltando segredo → :class:`ErroBackup` (só os nomes)."""
    faltando = [n for n in SEGREDOS_BACKUP if not (segredos.get(n) if segredos is not None else None)]
    if faltando:
        raise ErroBackup(f"segredos do backup faltando: {', '.join(faltando)}")
    return {
        "RESTIC_REPOSITORY": f"b2:{segredos.get('B2_BUCKET')}:magi",
        "RESTIC_PASSWORD": segredos.get("RESTIC_PASSWORD"),
        "B2_ACCOUNT_ID": segredos.get("B2_ACCOUNT_ID"),
        "B2_ACCOUNT_KEY": segredos.get("B2_ACCOUNT_KEY"),
        "RESTIC_CACHE_DIR": str(dados / "restic-cache"),
    }


def _snapshot_salvo(saida: str) -> str:
    m = _SNAPSHOT_SALVO.search(saida)
    if not m:
        raise ErroBackup("restic backup não disse o id do snapshot")
    return m.group(1)


def _desligado(deps: Deps) -> dict[str, Any] | None:
    if not deps.cfg.backup.ligado:
        log.info("backup desligado ([backup] ligado = false)")
        return {"pulado": "desligado"}
    return None


def _sha256(caminho: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    n = 0
    with open(caminho, "rb") as fh:
        while bloco := fh.read(1 << 20):
            h.update(bloco)
            n += len(bloco)
    return h.hexdigest(), n


# --------------------------------------------------------------------------- jobs


async def restic(
    deps: Deps, contexto: JobContext | None = None, *, origem: str = "pc", data: str | None = None
) -> dict[str, Any] | None:
    """Job da fila (dono: Y4.2).

    ``backup.restic``: ``restic backup`` de cada ``backups`` do PC ainda sem snapshot (só ``data``,
    se dada) e grava ``snapshot``/``enviado``."""
    if (p := _desligado(deps)) is not None:
        return p
    if origem != "pc":
        raise ValueError("backup.restic só sobe o backup do PC")
    sql = "SELECT data FROM backups WHERE origem = 'pc' AND snapshot IS NULL"
    args: list[Any] = []
    if data is not None:
        sql += " AND data = %s"
        args.append(data_valida(data))
    with deps.db.connection() as conn:
        datas = [r[0] for r in conn.execute(sql + " ORDER BY data", args).fetchall()]
    env = ambiente_restic(_segredos(deps), deps.dados) if datas else {}
    feitos: dict[str, str] = {}
    sem_arquivo: list[str] = []
    for d in datas:
        pasta = pasta_pc(deps.dados, d)
        if not arquivo_pc(deps.dados, d).exists():
            log.warning("backup.restic: entrada do pc sumiu (%s)", d)
            sem_arquivo.append(str(d))
            continue
        r = await _rodar(
            deps,
            Comando(
                ("restic", "backup", "--host", HOST, "--tag", "pc", "--tag", f"d{d}", str(pasta)), env=env
            ),
        )
        snap = _snapshot_salvo(r.saida)
        with deps.db.connection() as conn:
            conn.execute(
                "UPDATE backups SET snapshot = %s, enviado = %s WHERE origem = 'pc' AND data = %s",
                (snap, deps.relogio.agora(), d),
            )
        feitos[str(d)] = snap
    return {"snapshots": feitos, "sem_arquivo": sem_arquivo}


def _contagens(deps: Deps) -> dict[str, int | None]:
    from psycopg import sql

    saida: dict[str, int | None] = {}
    with deps.db.connection() as conn:
        for t in TABELAS_AYANAMI:
            if conn.execute("SELECT to_regclass(%s)", (t,)).fetchone()[0] is None:
                saida[t] = None
                continue
            q = sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(t))
            saida[t] = int(conn.execute(q).fetchone()[0])
    return saida


async def dump_ayanami(
    deps: Deps, contexto: JobContext | None = None, *, timestamp: int
) -> dict[str, Any] | None:
    """Job da fila (dono: Y4.2).

    ``backup.dump_ayanami``: ``pg_dump -Fc`` do ``ayanami-pg`` + manifesto + linha em ``backups``."""
    if (p := _desligado(deps)) is not None:
        return p
    d = _data_do(timestamp)
    pasta = pasta_ayanami(deps.dados, d)
    pasta.mkdir(parents=True, exist_ok=True)
    dump = pasta / DUMP_AYANAMI
    try:
        await _rodar(
            deps,
            Comando(("docker", "exec", PG_AYANAMI, "pg_dump", "-Fc", "-U", "ayanami", "ayanami"), saida=dump),
        )
    except BaseException:
        dump.unlink(missing_ok=True)
        raise
    versao = (
        await _rodar(
            deps, Comando(("docker", "exec", PG_AYANAMI, "pg_dump", "--version")), checar_codigo=False
        )
    ).saida.strip() or None
    manifesto = {"data": str(d), "pg_versao": versao, "tabelas": await asyncio.to_thread(_contagens, deps)}
    (pasta / MANIFESTO).write_text(json.dumps(manifesto, ensure_ascii=False), encoding="utf-8")
    sha, n = await asyncio.to_thread(_sha256, dump)
    with deps.db.connection() as conn:
        conn.execute(
            "INSERT INTO backups (origem, data, bytes, sha256, manifesto, recebido)"
            " VALUES ('ayanami', %s, %s, %s, %s, %s) ON CONFLICT (origem, data) DO UPDATE SET"
            " bytes = EXCLUDED.bytes, sha256 = EXCLUDED.sha256, manifesto = EXCLUDED.manifesto,"
            " recebido = EXCLUDED.recebido, snapshot = NULL, enviado = NULL",
            (d, n, sha, json.dumps(manifesto), deps.relogio.agora()),
        )
    return {"data": str(d), "bytes": n}


async def enviar(deps: Deps, contexto: JobContext | None = None, *, timestamp: int) -> dict[str, Any] | None:
    """Job da fila (dono: Y4.2).

    ``backup.enviar``: ``restic backup --tag ayanami`` do dump do dia e de ``/opt-config``; depois
    sobe o que do PC ficou sem snapshot."""
    if (p := _desligado(deps)) is not None:
        return p
    d = _data_do(timestamp)
    pasta = pasta_ayanami(deps.dados, d)
    if not (pasta / DUMP_AYANAMI).exists():
        raise ErroBackup(f"sem dump da Ayanami de {d}")
    opt = Path(deps.extras.get("opt_config") or OPT_CONFIG)
    env = ambiente_restic(_segredos(deps), deps.dados)
    r = await _rodar(
        deps, Comando(("restic", "backup", "--host", HOST, "--tag", "ayanami", str(pasta), str(opt)), env=env)
    )
    snap = _snapshot_salvo(r.saida)
    with deps.db.connection() as conn:
        conn.execute(
            "UPDATE backups SET snapshot = %s, enviado = %s WHERE origem = 'ayanami' AND data = %s",
            (snap, deps.relogio.agora(), d),
        )
    pc = await restic(deps, contexto)
    return {"snapshot": snap, "pc": pc}


async def reter(deps: Deps, contexto: JobContext | None = None, *, timestamp: int) -> dict[str, Any] | None:
    """Job da fila (dono: Y4.2).

    ``backup.reter`` [DS7]: ``forget --group-by host,tags`` com os três ``--keep-*``, por tag."""
    if (p := _desligado(deps)) is not None:
        return p
    env = ambiente_restic(_segredos(deps), deps.dados)
    for tag in ("pc", "ayanami"):
        await _rodar(
            deps,
            Comando(("restic", "forget", "--group-by", "host,tags", "--tag", tag, *KEEP, "--prune"), env=env),
        )
    return {"tags": ["pc", "ayanami"]}


async def verificar(
    deps: Deps, contexto: JobContext | None = None, *, timestamp: int
) -> dict[str, Any] | None:
    """Job da fila (dono: Y4.2).

    ``backup.verificar``: ``restic check --read-data-subset=5%``."""
    if (p := _desligado(deps)) is not None:
        return p
    env = ambiente_restic(_segredos(deps), deps.dados)
    await _rodar(deps, Comando(("restic", "check", "--read-data-subset=5%"), env=env))
    return {"ok": True}


def _telegram(deps: Deps) -> Any:
    t = deps.extras.get("telegram")
    if t is None:
        from ayanami import telegram

        t = telegram.de_segredos(_segredos(deps))
    return t


async def _avisar(deps: Deps, texto: str) -> bool:
    t = _telegram(deps)
    if t is None:
        log.warning("telegram_desligado")
        return False
    return bool(await t.enviar(texto))


def _achar_pacote(alvo: Path) -> Path:
    achados = sorted(alvo.rglob("magi-*.tar.zst"))
    if not achados:
        raise ErroBackup("snapshot sem pacote magi-*.tar.zst")
    return achados[-1]


def _ler_manifesto(extraido: Path, pacote: Path) -> dict[str, Any]:
    for c in (extraido / MANIFESTO, pacote.parent / MANIFESTO):
        if c.exists():
            m = json.loads(c.read_text(encoding="utf-8"))
            if isinstance(m, dict) and isinstance(m.get("tabelas"), dict):
                return m
    raise ErroBackup("manifesto ausente ou inválido")


async def _esperar_pronto(deps: Deps) -> None:
    # pelo TCP do loopback: durante o initdb o servidor temporário só ouve no socket
    cmd = Comando(("docker", "exec", RESTORE, "pg_isready", "-h", "127.0.0.1", "-U", "postgres"))
    for _ in range(TENTATIVAS_PRONTO):
        if (await _rodar(deps, cmd, checar_codigo=False)).codigo == 0:
            return
        await deps.relogio.dormir(ESPERA_PRONTO_S)
    raise ErroBackup("contêiner do restore de teste não ficou pronto")


def _apagar_alvo(dados: Path, alvo: Path) -> None:
    raiz = (dados / "tmp").resolve()
    real = alvo.resolve()
    if real.parent != raiz or not real.name.startswith("restore-"):
        raise ErroBackup("alvo do restore fora de /dados/tmp/restore-*")
    shutil.rmtree(real, ignore_errors=True)


async def restore_teste(
    deps: Deps, contexto: JobContext | None = None, *, timestamp: int
) -> dict[str, Any] | None:
    """Job da fila (dono: Y4.2).

    ``backup.restore_teste`` (R4.3): restaura o último snapshot ``pc`` num contêiner descartável
    sem rede, confere as contagens do manifesto (tolerância 0) e grava ``restore_testes``."""
    if (p := _desligado(deps)) is not None:
        return p
    if not deps.cfg.backup.restore_teste:
        return {"pulado": "restore_teste desligado"}
    alvo = deps.dados / "tmp" / f"restore-{uuid4().hex[:12]}"
    detalhes: dict[str, Any] = {}
    snapshot: str | None = None
    verde = False
    subiu = False
    try:
        env = ambiente_restic(_segredos(deps), deps.dados)
        alvo.mkdir(parents=True, exist_ok=True)
        r = await _rodar(
            deps, Comando(("restic", "restore", "latest", "--tag", "pc", "--target", str(alvo)), env=env)
        )
        m = _SNAPSHOT_RESTAURADO.search(r.saida)
        snapshot = m.group(1) if m else None
        pacote = _achar_pacote(alvo)
        extraido = alvo / "extraido"
        extraido.mkdir()
        await _rodar(deps, Comando(("tar", "--zstd", "-xf", str(pacote), "-C", str(extraido))))
        manifesto = _ler_manifesto(extraido, pacote)
        detalhes["data"] = manifesto.get("data")
        dump = extraido / DUMP_PC
        if not dump.exists():
            raise ErroBackup("pacote sem magi-pg.dump")
        subiu = True
        await _rodar(
            deps,
            Comando(
                (
                    "docker",
                    "run",
                    "-d",
                    "--rm",
                    "--name",
                    RESTORE,
                    "--network",
                    "none",
                    "-e",
                    "POSTGRES_PASSWORD",
                    IMAGEM_RESTORE,
                ),
                env={"POSTGRES_PASSWORD": secrets.token_urlsafe(24)},
            ),
        )
        await _esperar_pronto(deps)
        await _rodar(deps, Comando(("docker", "cp", str(dump), f"{RESTORE}:{DUMP_NO_CONTEINER}")))
        r = await _rodar(
            deps,
            Comando(
                (
                    "docker",
                    "exec",
                    RESTORE,
                    "pg_restore",
                    "--no-owner",
                    "-U",
                    "postgres",
                    "-d",
                    "postgres",
                    "--create",
                    DUMP_NO_CONTEINER,
                )
            ),
            checar_codigo=False,
        )
        detalhes["pg_restore_codigo"] = r.codigo  # avisos dão ≠ 0; quem decide são as contagens
        contagens: dict[str, int | None] = {}
        divergentes: dict[str, dict[str, Any]] = {}
        for tabela, esperado in sorted(manifesto["tabelas"].items()):
            if esperado is None:  # tabela que não existia no PC: não comparar
                continue
            achado: int | None = None
            if _IDENT.match(tabela):
                r = await _rodar(
                    deps,
                    Comando(
                        (
                            "docker",
                            "exec",
                            RESTORE,
                            "psql",
                            "-U",
                            "postgres",
                            "-d",
                            BASE_PC,
                            "-Atc",
                            f'SELECT count(*) FROM "{tabela}"',
                        )
                    ),
                    checar_codigo=False,
                )
                texto = r.saida.strip()
                achado = int(texto) if r.codigo == 0 and texto.isdigit() else None
            contagens[tabela] = achado
            if achado is None or achado != int(esperado):
                divergentes[tabela] = {"esperado": esperado, "achado": achado}
        detalhes["contagens"] = contagens
        detalhes["divergentes"] = divergentes
        if not contagens:
            detalhes["erro"] = "manifesto sem tabelas para comparar"
        verde = bool(contagens) and not divergentes
    except Exception as e:  # noqa: BLE001 — qualquer falha vira restore vermelho registrado
        detalhes["erro"] = f"{type(e).__name__}: {str(e)[:300]}"
        verde = False
    finally:
        if subiu:
            try:
                await _rodar(deps, Comando(("docker", "stop", RESTORE)), checar_codigo=False)
            except Exception as e:  # noqa: BLE001
                log.warning("restore_teste: docker stop falhou (%s)", type(e).__name__)
        try:
            await asyncio.to_thread(_apagar_alvo, deps.dados, alvo)
        except Exception as e:  # noqa: BLE001
            log.warning("restore_teste: não apagou o diretório (%s)", type(e).__name__)
    with deps.db.connection() as conn:
        conn.execute(
            "INSERT INTO restore_testes (ts, snapshot, verde, detalhes) VALUES (%s, %s, %s, %s)",
            (deps.relogio.agora(), snapshot, verde, json.dumps(detalhes, ensure_ascii=False)),
        )
    if verde:
        texto = (
            f"Ayanami: restore de teste verde (snapshot {snapshot}, {len(detalhes['contagens'])} tabelas)."
        )
    else:
        motivo = detalhes.get("erro") or "contagens diferentes: " + ", ".join(
            sorted(detalhes.get("divergentes", {}))
        )
        texto = f"Ayanami: restore de teste VERMELHO — {motivo}"[:500]
        from ayanami.eventos import criar_evento
        from magi.elo.mensagens import EventoTipo

        await asyncio.to_thread(
            criar_evento,
            deps.db,
            EventoTipo.BACKUP_FALHOU,
            "Restore de teste vermelho",
            texto[:200],
            None,
            agora=deps.relogio.agora(),
        )
    await _avisar(deps, texto)
    return {"verde": verde, "snapshot": snapshot, "detalhes": detalhes}


# --------------------------------------------------------------------------- CLI


def cli(
    args: Sequence[str], *, executor: Executor | None = None, env: Mapping[str, str] | None = None
) -> int:
    """``ayanami backup iniciar``: ``restic init`` (uma vez; repositório já existe → 0)."""
    args = list(args)
    if args[:1] != ["iniciar"]:
        print("uso: ayanami backup iniciar   (restic init no repositório b2 do .env)", file=sys.stderr)
        return 0 if args[:1] in (["-h"], ["--help"]) else 2
    fonte = dict(os.environ if env is None else env)
    dados = Path(fonte.get("AYANAMI_DADOS") or DADOS_PADRAO)
    try:
        ambiente = ambiente_restic(fonte, dados)
    except ErroBackup as e:
        print(f"ayanami backup iniciar: {e}", file=sys.stderr)
        return 2
    cmd = Comando(("restic", "init"), env=ambiente)
    checar_comando(cmd)
    r = (executor or executar)(cmd)
    if r.codigo == 0:
        print("repositório restic criado")
        return 0
    if "already" in r.erro or "existe" in r.erro:
        print("repositório restic já existe (nada feito)")
        return 0
    print(f"restic init falhou ({r.codigo}): {r.erro.strip()[-300:]}", file=sys.stderr)
    return 1
