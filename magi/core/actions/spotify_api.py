"""Spotify Web API: OAuth PKCE, busca por nome e reprodução no app local (R7.2).

API para outras tarefas (2.3 gosto, 2.4 sinais)::

    api = SpotifyApi()                         # tokens no keyring; renova sozinho
    await api.get("/me/top/artists", {"time_range": "short_term", "limit": 50})
    await api.search("numb", types=("track",))  # JSON cru do /v1/search
    m = await api.find("o álbum meteora")       # Match(kind="album", uri=..., name=...)
    play = make_play_query(mpris)               # PlayQuery para spotify_mpris.handlers()
    await play(req, "linkin park")              # busca e toca via SpotifyMpris.open_uri

Credenciais (keyring, serviço ``magi-assistant``): ``spotify-client-id`` (Client ID do app de
desenvolvedor; não é segredo, mas fica junto) e ``spotify-token`` (JSON com access/refresh
token, expiração e escopos), gravado por ``uv run python -m magi.cli.spotify_login``. Sem eles,
``play_query`` responde ``SAY_LOGIN``. O access token dura 1 h e é renovado com o refresh token
antes de vencer (ou após um 401); PKCE não usa client secret.

Escopos (``SCOPES``), o mínimo para 2.2-2.4: a busca não exige escopo;
``user-top-read`` (mais ouvidos, 3 prazos, 2.3), ``user-read-recently-played`` (recentes, 2.3),
``user-library-read`` (músicas curtidas, sinal de gosto) e ``playlist-read-private`` (ler as
playlists do usuário, inclusive privadas, para tocá-las pelo nome). Não pedimos
``user-modify-playback-state``: o controle é pelo MPRIS, que funciona sem Premium.

Limites: a reprodução usa o ``OpenUri`` do MPRIS, não o ``/me/player/play`` (que exige Premium).
Faixa abre e toca; álbum, playlist e artista abrem o contexto no app e, nas versões atuais do
cliente Linux, começam a tocar, mas o Spotify pode só abrir a página (sem Premium o app também
pode embaralhar e inserir anúncios). Apps em modo de desenvolvimento só atendem as contas
cadastradas no painel do app, e a busca é limitada a poucos resultados por tipo (usamos 5).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets as _rand
import time
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
from rapidfuzz import fuzz

from magi.common import secrets
from magi.common.contracts import ActionRequest, ActionResult, Expression
from magi.core.actions.spotify_mpris import (
    SAY_DBUS_FAILED,
    SAY_NOT_STARTED,
    MprisError,
    PlayQuery,
    SpotifyMpris,
    SpotifyNotRunning,
)

log = logging.getLogger(__name__)

CLIENT_ID_KEY = "spotify-client-id"
TOKEN_KEY = "spotify-token"
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_URL = "https://api.spotify.com/v1"
DEFAULT_PORT = 8765
SCOPES = ("user-top-read", "user-read-recently-played", "user-library-read", "playlist-read-private")
SEARCH_TYPES = ("artist", "track", "album", "playlist")
SEARCH_LIMIT = 5
REFRESH_MARGIN_S = 60.0
MIN_SCORE = 60.0  # abaixo disso, sem tipo citado, vale a ordem de relevância do Spotify

SAY_LOGIN = "Preciso que você conecte o Spotify primeiro (magi-spotify-login)."
SAY_API_FAILED = "Não consegui falar com o Spotify."


def redirect_uri(port: int = DEFAULT_PORT) -> str:
    """Redirect URI a cadastrar no app (Spotify exige 127.0.0.1 literal, não ``localhost``)."""
    return f"http://127.0.0.1:{port}/callback"


class SpotifyAuthError(RuntimeError):
    """Sem client id/token, ou o refresh token foi revogado: rodar o login de novo."""


class SpotifyApiError(RuntimeError):
    """Resposta de erro da Web API (status != 2xx)."""

    def __init__(self, status: int, detail: str = "") -> None:
        super().__init__(f"Spotify {status}: {detail}")
        self.status = status


# --- tokens ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Token:
    access_token: str
    refresh_token: str
    expires_at: float  # epoch, s
    scope: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))

    @classmethod
    def from_json(cls, raw: str) -> Token:
        d = json.loads(raw)
        return cls(d["access_token"], d["refresh_token"], float(d["expires_at"]), d.get("scope", ""))

    @classmethod
    def from_response(cls, d: Mapping[str, Any], now: float, old_refresh: str = "") -> Token:
        # O refresh pode não devolver refresh_token novo: mantém o anterior.
        return cls(
            access_token=d["access_token"],
            refresh_token=d.get("refresh_token") or old_refresh,
            expires_at=now + float(d.get("expires_in", 3600)),
            scope=d.get("scope", ""),
        )


class TokenStore:
    """Client id e token no keyring (via ``magi.common.secrets``). Funções injetáveis em teste."""

    def __init__(
        self,
        get: Callable[[str], str | None] = secrets.get_secret,
        set: Callable[[str, str], None] = secrets.set_secret,  # noqa: A002
    ) -> None:
        self._get, self._set = get, set

    def client_id(self) -> str | None:
        return (self._get(CLIENT_ID_KEY) or "").strip() or None

    def set_client_id(self, value: str) -> None:
        self._set(CLIENT_ID_KEY, value.strip())

    def load(self) -> Token | None:
        raw = self._get(TOKEN_KEY)
        if not raw:
            return None
        try:
            return Token.from_json(raw)
        except (ValueError, KeyError, TypeError):
            log.warning("token do Spotify no keyring está corrompido")
            return None

    def save(self, token: Token) -> None:
        self._set(TOKEN_KEY, token.to_json())


# --- PKCE --------------------------------------------------------------------------------------


def make_verifier() -> str:
    """code_verifier de 64 caracteres (43..128 permitidos)."""
    return _rand.token_urlsafe(48)


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorize_url(
    client_id: str, redirect: str, challenge: str, state: str, scopes: Iterable[str] = SCOPES
) -> str:
    q = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "state": state,
        "scope": " ".join(scopes),
    }
    return f"{AUTH_URL}?{urlencode(q)}"


async def _token_request(client: httpx.AsyncClient, data: Mapping[str, str]) -> dict[str, Any]:
    r = await client.post(TOKEN_URL, data=dict(data))
    if r.status_code in (400, 401):
        raise SpotifyAuthError(f"token recusado: {r.text[:200]}")
    if r.status_code >= 300:
        raise SpotifyApiError(r.status_code, r.text[:200])
    return r.json()


async def exchange_code(
    client: httpx.AsyncClient, client_id: str, code: str, verifier: str, redirect: str,
    now: float | None = None,
) -> Token:
    """Troca o ``code`` do callback pelo token (fim do fluxo PKCE)."""
    d = await _token_request(client, {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect,
        "client_id": client_id,
        "code_verifier": verifier,
    })
    return Token.from_response(d, time.time() if now is None else now)


async def refresh_token(
    client: httpx.AsyncClient, client_id: str, token: Token, now: float | None = None
) -> Token:
    d = await _token_request(client, {
        "grant_type": "refresh_token",
        "refresh_token": token.refresh_token,
        "client_id": client_id,
    })
    return Token.from_response(d, time.time() if now is None else now, token.refresh_token)


# --- cliente da Web API ------------------------------------------------------------------------


class SpotifyApi:
    """Cliente assíncrono da Web API com renovação automática do token."""

    def __init__(
        self,
        store: TokenStore | None = None,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store or TokenStore()
        self._client = client
        self._clock = clock
        self._token: Token | None = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    def connected(self) -> bool:
        """Há client id e token no keyring (não valida na rede)."""
        return bool(self.store.client_id() and self.store.load())

    async def _refresh(self, client_id: str, tok: Token) -> Token:
        tok = await refresh_token(self._http(), client_id, tok, self._clock())
        self.store.save(tok)
        self._token = tok
        return tok

    async def access_token(self, force_refresh: bool = False) -> str:
        client_id = self.store.client_id()
        tok = self._token or self.store.load()
        if not client_id or tok is None:
            raise SpotifyAuthError("Spotify não conectado")
        if force_refresh or tok.expires_at - REFRESH_MARGIN_S <= self._clock():
            tok = await self._refresh(client_id, tok)
        self._token = tok
        return tok.access_token

    async def get(self, path: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """GET autenticado em ``API_URL + path``; renova e repete uma vez após 401."""
        url = path if path.startswith("http") else f"{API_URL}{path}"
        for attempt in (0, 1):
            tok = await self.access_token(force_refresh=attempt == 1)
            r = await self._http().get(
                url, params=dict(params or {}), headers={"Authorization": f"Bearer {tok}"}
            )
            if r.status_code == 401 and attempt == 0:
                continue
            if r.status_code >= 300:
                raise SpotifyApiError(r.status_code, r.text[:200])
            return r.json() if r.content else {}
        raise AssertionError("inalcançável")  # pragma: no cover

    async def search(
        self, query: str, types: Iterable[str] = SEARCH_TYPES, limit: int = SEARCH_LIMIT
    ) -> dict[str, Any]:
        return await self.get(
            "/search",
            {"q": query, "type": ",".join(types), "limit": limit, "market": "from_token"},
        )

    async def find(self, query: str) -> Match | None:
        """Interpreta o pedido ("o álbum X", "a playlist Y", "Linkin Park") e escolhe o resultado."""
        kind, text = parse_query(query)
        if not text:
            return None
        types = (kind,) if kind else SEARCH_TYPES
        return choose(await self.search(text, types), text, kind)


# --- escolha do resultado ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Match:
    kind: str  # "track" | "artist" | "album" | "playlist"
    uri: str
    name: str
    artist: str = ""  # artista principal (faixa/álbum) ou dono (playlist)
    score: float = 0.0


# Prefixos que citam o tipo (comparados sem acento e em minúsculas, por palavras inteiras).
_KIND_PREFIXES: tuple[tuple[str, str], ...] = tuple(
    (p, kind)
    for kind, ps in (
        ("album", ("o album", "album", "o disco", "disco", "o cd", "cd")),
        ("playlist", ("a playlist", "playlist", "a lista", "minha playlist")),
        ("artist", (
            "musicas do", "musicas da", "musicas de", "o artista", "artista", "a artista",
            "a banda", "banda", "o cantor", "cantor", "a cantora", "cantora", "o grupo",
            "o rapper", "a rapper", "o dj",
        )),
        ("track", ("a musica", "musica", "a faixa", "faixa", "a cancao", "cancao")),
    )
    for p in ps
)
_CONNECTIVES = (" de ", " do ", " da ", " dos ", " das ", " by ")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.casefold())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join("".join(c if c.isalnum() else " " for c in s).split())


def parse_query(query: str) -> tuple[str | None, str]:
    """``("album", "meteora")`` para "o álbum Meteora"; ``(None, texto)`` sem tipo citado."""
    words = query.split()
    norm = [_norm(w) for w in words]
    for prefix, kind in sorted(_KIND_PREFIXES, key=lambda pk: -len(pk[0])):
        pw = prefix.split()
        if norm[: len(pw)] == pw and len(words) > len(pw):
            return kind, " ".join(words[len(pw):]).strip()
    return None, query.strip()


def _artist_of(item: Mapping[str, Any]) -> str:
    arts = item.get("artists") or []
    if arts and isinstance(arts[0], Mapping):
        return str(arts[0].get("name", ""))
    owner = item.get("owner") or {}
    return str(owner.get("display_name") or "")


def _score(kind: str, item: Mapping[str, Any], q: str) -> float:
    name = _norm(str(item.get("name", "")))
    s = fuzz.ratio(q, name)
    if kind in ("track", "album"):
        artist = _norm(_artist_of(item))
        s = max(s, fuzz.ratio(q, f"{name} {artist}"))
        padded = f" {q} "
        for c in _CONNECTIVES:  # "numb do linkin park" = nome + artista
            if c in padded:
                left, _, right = padded.partition(c)
                s = max(s, (fuzz.ratio(left.strip(), name) + fuzz.ratio(right.strip(), artist)) / 2)
    return float(s)


# Desempate a favor do tipo mais provável quando o nome bate igual ("toca Linkin Park").
_KIND_BONUS = {"artist": 3.0, "track": 2.0, "album": 1.0, "playlist": 0.0}


def choose(results: Mapping[str, Any], text: str, kind: str | None = None) -> Match | None:
    """Escolhe o melhor resultado do ``/v1/search``. Com ``kind``, só aquele tipo.

    Sem tipo citado: maior semelhança do nome com o pedido (com bônus pequeno por tipo e
    penalidade pela posição na lista do Spotify). Se nada passa de ``MIN_SCORE``, fica o primeiro
    resultado da relevância do Spotify: faixa, depois artista, álbum, playlist.
    """
    q = _norm(text)
    best: tuple[float, Match] | None = None
    first: dict[str, Match] = {}
    for k in (kind,) if kind else SEARCH_TYPES:
        items = [i for i in (results.get(f"{k}s") or {}).get("items") or [] if i and i.get("uri")]
        for rank, item in enumerate(items):
            s = _score(k, item, q)
            m = Match(k, item["uri"], str(item.get("name", "")), _artist_of(item), s)
            first.setdefault(k, m)
            ranked = s - 2.0 * rank + _KIND_BONUS[k]
            if best is None or ranked > best[0]:
                best = (ranked, m)
    if best is None:
        return None
    if kind or best[1].score >= MIN_SCORE:
        return best[1]
    return next((first[k] for k in ("track", "artist", "album", "playlist") if k in first), None)


def speech_for(m: Match) -> str:
    if m.kind == "track":
        return f"Tocando {m.name}, de {m.artist}." if m.artist else f"Tocando {m.name}."
    if m.kind == "album":
        return f"Tocando o álbum {m.name}, de {m.artist}." if m.artist else f"Tocando o álbum {m.name}."
    if m.kind == "playlist":
        return f"Tocando a playlist {m.name}."
    return f"Tocando {m.name}."


# --- ação: tocar por nome ----------------------------------------------------------------------


class SpotifyPlayer:
    """Implementa ``PlayQuery`` (``music.play`` com slot ``query``) de ``spotify_mpris``."""

    def __init__(self, mpris: SpotifyMpris, api: SpotifyApi | None = None) -> None:
        self.mpris = mpris
        self.api = api or SpotifyApi()

    async def play_query(self, req: ActionRequest, query: str) -> ActionResult:
        confused = Expression.CONFUSED
        try:
            m = await self.api.find(query)
        except SpotifyAuthError:
            return ActionResult(ok=False, speech=SAY_LOGIN, expression=confused)
        except (SpotifyApiError, httpx.HTTPError) as e:
            log.warning("Spotify Web API falhou: %r", e)
            return ActionResult(ok=False, speech=SAY_API_FAILED, expression=confused)
        if m is None:
            return ActionResult(ok=False, speech=f"Não achei {query} no Spotify.", expression=confused)
        try:
            await self.mpris.open_uri(m.uri)
        except SpotifyNotRunning:
            return ActionResult(ok=False, speech=SAY_NOT_STARTED, expression=confused)
        except (MprisError, OSError) as e:
            log.warning("OpenUri falhou: %r", e)
            return ActionResult(ok=False, speech=SAY_DBUS_FAILED, expression=confused)
        return ActionResult(ok=True, speech=speech_for(m))

    __call__ = play_query


def make_play_query(mpris: SpotifyMpris, api: SpotifyApi | None = None) -> PlayQuery:
    """Para ``spotify_mpris.handlers(mpris, play_query=make_play_query(mpris))``."""
    return SpotifyPlayer(mpris, api).play_query
