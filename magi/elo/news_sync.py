"""``magi-news-sync``: o PC puxa as notícias da Ayanami para o ``magi-pg`` (spec §5.2, design §8).

::

    magi-news-sync [--config P] [--dsn D] [--precisa-local] [-v]
      sem flag: puxa páginas até "fim": true; exit 0 ok, 2 Ayanami fora, 3 erro de banco
      --precisa-local: exit 0 = deve coletar local (último OK > 6 h E há internet); exit 1 = não

Estado em ``$XDG_STATE_HOME/magi/news_sync.json`` (padrão ``~/.local/state/magi``):
``{"cursor": str|null, "ultimo_ok": ts|null}``. URL da Ayanami em ``[ayanami] url`` do
``config.toml``; token do PC por ``magi.elo.credenciais.token_pc`` (keyring ``magi``/``ayanami_pc``,
recaída ``ayanami.token`` ao lado do ``config.toml``), nunca em log.

Sem ``[ayanami]`` (ou sem ``url``) o PC fica como hoje: ``--precisa-local`` sai 0 (a coleta local
roda) e a sincronização não faz nada (exit 0). ``--precisa-local`` é o ``ExecCondition=`` do
``magi-ayanami.service``: qualquer erro inesperado nele também sai 0 (na dúvida, coleta local).

*Upsert* numa transação por página: ``news_sources`` e ``news_raw`` por ``url``; ``news_items`` por
``ayanami_uid`` (tudo menos ``delivered_at``, que é do PC); um item local sem ``ayanami_uid`` que já
cite uma das cruas do item da nuvem é adotado (ganha o ``ayanami_uid``, mantém ``delivered_at``),
para a mesma notícia não ser entregue duas vezes; ``news_item_sources`` recriado só para o item.
Embedding com tamanho diferente da coluna (``NEWS_DIM``) vira ``NULL`` + log. Depois do sync OK,
``PUT /v1/noticias/preferencias`` com ``franchise_prefs`` e ``progress`` do PC.

Imports pesados (``httpx``, ``psycopg``, ``keyring``) são locais: o caminho ``--precisa-local`` só
usa a biblioteca padrão, para o ``ExecCondition`` não falhar por dependência.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from magi.elo.credenciais import KEYRING_NOME, KEYRING_SERVICO, TOKEN_FILE, token_pc, url_ayanami

if TYPE_CHECKING:
    import httpx
    import psycopg

log = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_NAO = 1  # --precisa-local: não coletar local
EXIT_AYANAMI_FORA = 2
EXIT_BANCO = 3

LIMITE_LOCAL = timedelta(hours=6)
PAGINA_N = 200
MAX_PAGINAS = 1000
INTERNET = ("1.1.1.1", 443)
DEFAULT_DSN = "postgresql://magi:magi@127.0.0.1:54329/magi"

Relogio = Callable[[], datetime]
Internet = Callable[[], bool]
Token = Callable[[], str | None]


class AyanamiFora(RuntimeError):
    """A Ayanami não respondeu como esperado (rede, HTTP ≠ 2xx, JSON inválido)."""


# --- estado ---------------------------------------------------------------------------------------


@dataclass
class Estado:
    cursor: str | None = None
    ultimo_ok: datetime | None = None


def caminho_estado() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or "~/.local/state"
    return Path(base).expanduser() / "magi" / "news_sync.json"


def ler_estado(caminho: Path) -> Estado:
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Estado()
    except (OSError, ValueError) as e:
        log.warning("estado ilegível em %s (%s): começando do zero", caminho, e)
        return Estado()
    if not isinstance(dados, dict):
        return Estado()
    cursor = dados.get("cursor")
    ok = dados.get("ultimo_ok")
    try:
        ultimo_ok = datetime.fromisoformat(ok) if isinstance(ok, str) else None
    except ValueError:
        ultimo_ok = None
    if ultimo_ok is not None and ultimo_ok.tzinfo is None:
        ultimo_ok = ultimo_ok.replace(tzinfo=UTC)
    return Estado(cursor=cursor if isinstance(cursor, str) else None, ultimo_ok=ultimo_ok)


def gravar_estado(caminho: Path, estado: Estado) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_name(caminho.name + ".tmp")
    tmp.write_text(
        json.dumps(
            {
                "cursor": estado.cursor,
                "ultimo_ok": estado.ultimo_ok.isoformat() if estado.ultimo_ok else None,
            }
        ),
        encoding="utf-8",
    )
    os.replace(tmp, caminho)


# --- recaída local --------------------------------------------------------------------------------


def tem_internet(conectar: Callable[..., Any] = socket.create_connection) -> bool:
    try:
        s = conectar(INTERNET, 3)
    except OSError:
        return False
    try:
        s.close()
    except Exception:  # noqa: BLE001 - socket falso sem close
        pass
    return True


def precisa_local(estado: Estado, agora: datetime, internet: Internet) -> bool:
    """Coleta local só se o último sync OK tem mais de 6 h (ou nunca houve) **e** há internet."""
    if estado.ultimo_ok is not None and agora - estado.ultimo_ok <= LIMITE_LOCAL:
        return False
    return internet()


# --- config ---------------------------------------------------------------------------------------


@dataclass
class ConfigSync:
    url: str | None
    dsn: str | None
    dir: Path


def ler_config(caminho: str | None) -> ConfigSync:
    """Lê só ``[ayanami] url`` e ``[database] dsn``; arquivo ausente = sem ``[ayanami]``."""
    if caminho:
        p = Path(caminho).expanduser()
    else:
        from magi.common.config import config_path

        p = config_path()
    try:
        with p.open("rb") as f:
            dados = tomllib.load(f)
    except FileNotFoundError:
        return ConfigSync(url=None, dsn=None, dir=p.parent)
    db = dados.get("database")
    dsn = db.get("dsn") if isinstance(db, dict) else None
    return ConfigSync(
        url=url_ayanami(dados), dsn=dsn if isinstance(dsn, str) and dsn else None, dir=p.parent
    )


# --- cliente HTTP ---------------------------------------------------------------------------------


class ClienteAyanami:
    def __init__(self, cliente: httpx.Client) -> None:
        self.cliente = cliente

    def _pedir(self, metodo: str, rota: str, **kw: Any) -> httpx.Response:
        import httpx

        try:
            r = self.cliente.request(metodo, rota, **kw)
        except httpx.HTTPError as e:
            raise AyanamiFora(f"{metodo} {rota}: {type(e).__name__}") from e
        if r.status_code // 100 != 2:
            raise AyanamiFora(f"{metodo} {rota}: HTTP {r.status_code}")
        return r

    def pagina(self, cursor: str | None) -> dict[str, Any]:
        params: dict[str, Any] = {"n": PAGINA_N}
        if cursor:
            params["desde"] = cursor
        r = self._pedir("GET", "/v1/noticias", params=params)
        try:
            dados = r.json()
        except ValueError as e:
            raise AyanamiFora("GET /v1/noticias: JSON inválido") from e
        if not isinstance(dados, dict):
            raise AyanamiFora("GET /v1/noticias: resposta não é objeto")
        return dados

    def preferencias(self, dados: dict[str, Any]) -> None:
        self._pedir("PUT", "/v1/noticias/preferencias", json=dados)


# --- banco ----------------------------------------------------------------------------------------


def dimensao_embedding(conn: psycopg.Connection) -> int | None:
    """``NEWS_DIM`` real: o ``atttypmod`` da coluna ``vector(n)`` é ``n``."""
    row = conn.execute(
        "SELECT atttypmod FROM pg_attribute "
        "WHERE attrelid = 'news_items'::regclass AND attname = 'embedding'"
    ).fetchone()
    return int(row[0]) if row and row[0] and row[0] > 0 else None


def _vec(embedding: Any, dim: int | None, uid: str) -> str | None:
    if embedding is None:
        return None
    if not isinstance(embedding, list) or (dim is not None and len(embedding) != dim):
        n = len(embedding) if isinstance(embedding, list) else "?"
        log.warning("item %s: embedding com %s dimensões (esperado %s) → NULL", uid, n, dim)
        return None
    return "[" + ",".join(repr(float(x)) for x in embedding) + "]"


_COLS_ITEM = (
    "title, summary, embedding, first_seen, sources, max_trust, franchise, kind, spoiler, priority, level"
)


def _upsert_item(conn: psycopg.Connection, item: dict[str, Any], dim: int | None) -> int:
    from psycopg.types.json import Jsonb

    uid = str(item["uid"])
    urls = [u for u in item.get("brutos") or [] if isinstance(u, str)]
    spoiler = item.get("spoiler")
    valores = [
        item["title"],
        item.get("summary"),
        _vec(item.get("embedding"), dim, uid),
        item.get("first_seen"),
        item.get("sources") or 1,
        item.get("max_trust"),
        item.get("franchise"),
        item.get("kind"),
        Jsonb(spoiler) if spoiler is not None else None,
        item.get("priority"),
        item.get("level"),
    ]
    row = conn.execute("SELECT id FROM news_items WHERE ayanami_uid = %s", [uid]).fetchone()
    if row is None and urls:
        # Item local (coleta de recaída) com a mesma crua: adota em vez de duplicar.
        row = conn.execute(
            """
            SELECT i.id FROM news_items i
            JOIN news_item_sources s ON s.item_id = i.id
            JOIN news_raw r ON r.id = s.raw_id
            WHERE i.ayanami_uid IS NULL AND r.url = ANY(%s)
            ORDER BY i.id LIMIT 1
            """,
            [urls],
        ).fetchone()
    if row is not None:
        item_id = int(row[0])
        conn.execute(
            """
            UPDATE news_items SET ayanami_uid = %s, title = %s, summary = %s, embedding = %s::vector,
                first_seen = COALESCE(%s, first_seen), sources = %s, max_trust = %s, franchise = %s,
                kind = %s, spoiler = %s, priority = %s, level = %s
            WHERE id = %s
            """,
            [uid, *valores, item_id],
        )
    else:
        cur = conn.execute(
            f"""
            INSERT INTO news_items (ayanami_uid, {_COLS_ITEM})
            VALUES (%s, %s, %s, %s::vector, COALESCE(%s, now()), %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            [uid, *valores],
        )
        got = cur.fetchone()
        assert got is not None
        item_id = int(got[0])
    conn.execute("DELETE FROM news_item_sources WHERE item_id = %s", [item_id])
    if urls:
        conn.execute(
            """
            INSERT INTO news_item_sources (item_id, raw_id)
            SELECT %s, id FROM news_raw WHERE url = ANY(%s)
            ON CONFLICT DO NOTHING
            """,
            [item_id, urls],
        )
    return item_id


def aplicar_pagina(conn: psycopg.Connection, pagina: dict[str, Any], dim: int | None) -> int:
    """Grava uma página numa transação só; devolve quantos itens vieram."""
    itens = pagina.get("itens") or []
    with conn.transaction():
        for f in pagina.get("fontes") or []:
            conn.execute(
                """
                INSERT INTO news_sources (name, kind, url, trust) VALUES (%s, %s, %s, %s)
                ON CONFLICT (url) DO UPDATE
                    SET name = EXCLUDED.name, kind = EXCLUDED.kind, trust = EXCLUDED.trust
                """,
                [f["name"], f["kind"], f["url"], f.get("trust") or 1],
            )
        for b in pagina.get("brutos") or []:
            conn.execute(
                """
                INSERT INTO news_raw (source_id, url, title, body, published_at, fetched_at)
                VALUES ((SELECT id FROM news_sources WHERE url = %s), %s, %s, %s, %s,
                        COALESCE(%s, now()))
                ON CONFLICT (url) DO UPDATE SET
                    source_id = COALESCE(EXCLUDED.source_id, news_raw.source_id),
                    title = EXCLUDED.title, body = EXCLUDED.body,
                    published_at = EXCLUDED.published_at, fetched_at = EXCLUDED.fetched_at
                """,
                [b.get("fonte_url"), b["url"], b.get("title"), b.get("body"), b.get("published_at"),
                 b.get("fetched_at")],
            )
        for item in itens:
            _upsert_item(conn, item, dim)
    return len(itens)


def preferencias_do_pc(conn: psycopg.Connection) -> dict[str, Any]:
    prefs = conn.execute(
        "SELECT franchise, weight, dropped, spoilers_ok FROM franchise_prefs ORDER BY franchise"
    ).fetchall()
    prog = conn.execute(
        "SELECT franchise, kind, value, updated_at FROM progress ORDER BY franchise, kind"
    ).fetchall()
    return {
        "franchise_prefs": [
            {"franchise": f, "weight": float(w), "dropped": d, "spoilers_ok": s} for f, w, d, s in prefs
        ],
        "progress": [
            {"franchise": f, "kind": k, "value": v, "updated_at": u.isoformat() if u else None}
            for f, k, v, u in prog
        ],
    }


# --- sincronização --------------------------------------------------------------------------------


def sincronizar(
    conn: psycopg.Connection,
    api: ClienteAyanami,
    caminho: Path,
    agora: Relogio,
) -> int:
    """Puxa páginas até ``fim``; grava o cursor depois de cada página. Devolve o código de saída."""
    import psycopg

    estado = ler_estado(caminho)
    try:
        dim = dimensao_embedding(conn)
        total = 0
        for _ in range(MAX_PAGINAS):
            pagina = api.pagina(estado.cursor)
            total += aplicar_pagina(conn, pagina, dim)
            novo = pagina.get("cursor")
            fim = bool(pagina.get("fim"))
            if not fim and (not novo or novo == estado.cursor):
                raise AyanamiFora("cursor não avançou com fim=false")
            if novo:
                estado.cursor = str(novo)
            gravar_estado(caminho, estado)
            if fim:
                break
        else:
            raise AyanamiFora(f"mais de {MAX_PAGINAS} páginas sem fim")
        estado.ultimo_ok = agora()
        gravar_estado(caminho, estado)
        log.info("news-sync: %d itens; cursor %s", total, estado.cursor)
        prefs = preferencias_do_pc(conn)
    except AyanamiFora as e:
        log.error("Ayanami fora: %s", e)
        return EXIT_AYANAMI_FORA
    except psycopg.Error as e:
        log.error("erro de banco: %s", type(e).__name__)
        return EXIT_BANCO
    try:
        api.preferencias(prefs)
    except AyanamiFora as e:
        log.warning("preferências não enviadas: %s", e)
    return EXIT_OK


# --- entrada --------------------------------------------------------------------------------------


def _agora() -> datetime:
    return datetime.now(UTC)


def main(
    argv: list[str] | None = None,
    *,
    transporte: httpx.BaseTransport | None = None,
    internet: Internet | None = None,
    agora: Relogio = _agora,
    token: Token | None = None,
    estado_em: Path | None = None,
) -> int:
    ap = argparse.ArgumentParser(prog="magi-news-sync", description="Puxa as notícias da Ayanami.")
    ap.add_argument("--config", help="caminho do config.toml (padrão: $MAGI_CONFIG ou ~/.config/magi)")
    ap.add_argument("--dsn", help="DSN do Postgres do PC")
    ap.add_argument("--precisa-local", action="store_true", help="exit 0 = coletar local; 1 = não")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.DEBUG if args.verbose else logging.WARNING)
    caminho = estado_em or caminho_estado()

    if args.precisa_local:
        try:
            cfg = ler_config(args.config)
            if cfg.url is None:
                return EXIT_OK  # sem [ayanami]: a coleta local roda como hoje
            sim = precisa_local(ler_estado(caminho), agora(), internet or tem_internet)
        except Exception as e:  # noqa: BLE001 - na dúvida, coleta local
            log.warning("precisa-local: %s; coletando local", type(e).__name__)
            return EXIT_OK
        log.info("coleta local: %s", "sim" if sim else "não")
        return EXIT_OK if sim else EXIT_NAO

    try:
        cfg = ler_config(args.config)
    except (OSError, tomllib.TOMLDecodeError) as e:
        log.error("config ilegível: %s", e)
        return EXIT_AYANAMI_FORA
    if cfg.url is None:
        log.info("sem [ayanami] url no config: nada a sincronizar")
        return EXIT_OK
    chave = token() if token else token_pc(cfg.dir)
    if not chave:
        log.error("sem token do PC (keyring %s/%s nem %s)", KEYRING_SERVICO, KEYRING_NOME, TOKEN_FILE)
        return EXIT_AYANAMI_FORA
    dsn = args.dsn or cfg.dsn or os.environ.get("MAGI_DB_DSN") or DEFAULT_DSN

    import httpx
    import psycopg

    try:
        conn = psycopg.connect(dsn, connect_timeout=5, autocommit=True)
    except psycopg.Error as e:
        log.error("erro de banco: %s", type(e).__name__)
        return EXIT_BANCO
    try:
        with httpx.Client(
            base_url=cfg.url,
            headers={"Authorization": f"Bearer {chave}"},
            timeout=20,
            transport=transporte,
        ) as cliente:
            return sincronizar(conn, ClienteAyanami(cliente), caminho, agora)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
