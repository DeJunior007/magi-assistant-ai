"""Mensagens do elo: envelope JSON, os 12 corpos, ``encode``/``decode`` (spec §1.1–§1.3).

Puro: sem I/O. ``decode`` valida tudo da §1.3 e nunca devolve corpo parcial; campos
desconhecidos (no envelope e nos corpos) são ignorados. Os datetimes viajam em UTC com "Z" e
milissegundos; o ``Envelope`` normaliza ``ts`` para UTC truncado em ms, então
``decode(encode(env)) == env``.
"""

from __future__ import annotations

import dataclasses
import json
import re
import types
import typing
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, StrEnum
from typing import Any, Final

from magi.elo.ids import novo_id, valido

VERSAO: Final = 1
MAX_TEXTO_BYTES: Final = 65_536  # frame de texto WS / corpo JSON do long-poll
MAX_BINARIO_BYTES: Final = 8_192  # frame binário (§1.4)
NOME_RE: Final = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")  # nomes de dispositivo; "ayanami" reservado

MAX_TURNO_TEXTO: Final = 4000
MAX_TURNO_FIM_TEXTO: Final = 16_000
MAX_DADOS_BYTES: Final = 4096
MAX_TVS: Final = 16
MAX_RESUMO_TURNOS: Final = 50
MAX_EVENTO_TITULO: Final = 80
MAX_EVENTO_RESUMO: Final = 200
MAX_ERRO_MSG: Final = 200
PRAZO_MIN_MS: Final = 500
PRAZO_MAX_MS: Final = 30_000


class EloError(ValueError):
    """Erro de validação do elo. ``codigo``: "json" | "versao" | "tipo" | "campo" | "tamanho" | "nome"."""

    def __init__(self, codigo: str, msg: str = "") -> None:
        super().__init__(f"{codigo}: {msg}" if msg else codigo)
        self.codigo = codigo


class Tipo(StrEnum):
    OLA = "ola"
    BATE = "bate"
    TURNO = "turno"
    TURNO_FIM = "turno_fim"
    ACAO = "acao"
    ACAO_OK = "acao_ok"
    ESTADO = "estado"
    EVENTO = "evento"
    CONFIRMA = "confirma"
    RESUMO_NUVEM = "resumo_nuvem"
    ACK = "ack"
    ERRO = "erro"


#: Tipos cujo emissor espera resposta (reenvio com o mesmo id, §1.3).
PEDE_RESPOSTA: Final = frozenset(
    {Tipo.OLA, Tipo.TURNO, Tipo.TURNO_FIM, Tipo.ACAO, Tipo.EVENTO, Tipo.CONFIRMA, Tipo.RESUMO_NUVEM}
)


def agora_utc() -> datetime:
    """Agora em UTC, truncado em milissegundos (a precisão do fio)."""
    return _trunca_ms(datetime.now(UTC))


def _trunca_ms(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(microsecond=dt.microsecond // 1000 * 1000)


def formata_ts(dt: datetime) -> str:
    """``datetime`` com fuso → ``"2026-10-12T21:04:05.123Z"``."""
    if dt.tzinfo is None:
        raise EloError("campo", "datetime sem fuso")
    u = dt.astimezone(UTC)
    return u.strftime("%Y-%m-%dT%H:%M:%S.") + f"{u.microsecond // 1000:03d}Z"


def le_ts(s: object, caminho: str = "ts") -> datetime:
    """Texto ISO 8601 com fuso → ``datetime`` UTC. Sem fuso ou malformado → ``EloError("campo")``."""
    if not isinstance(s, str):
        raise EloError("campo", f"{caminho}: esperado texto ISO 8601")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as e:
        raise EloError("campo", f"{caminho}: data inválida") from e
    if dt.tzinfo is None:
        raise EloError("campo", f"{caminho}: data sem fuso")
    return dt.astimezone(UTC)


# ---------------------------------------------------------------------------------------------
# Corpos (§1.2)
# ---------------------------------------------------------------------------------------------


class TipoDispositivo(StrEnum):
    PC = "pc"
    CASA = "casa"
    CELULAR = "celular"
    MCP = "mcp"


@dataclass(frozen=True, slots=True)
class TvInfo:
    """[DS19] Parte fixa da TV (casa.toml + capacidades), no ``ola`` da casa."""

    id: str
    nome: str
    driver: str  # "samsung" | "roku" | "androidtv"
    apelidos: tuple[str, ...] = ()
    caps: tuple[str, ...] = ()  # valores de Cap (§10.5), já com as emuladas
    entradas: tuple[str, ...] = ()
    apps: tuple[str, ...] = ()
    padrao: bool = False


@dataclass(frozen=True, slots=True)
class AppInfo:
    id: str
    nome: str
    apelidos: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EstadoTv:
    """[DS19] Tipo único do estado vivo da TV."""

    id: str
    nome: str
    driver: str
    online: bool  # respondeu à última sondagem/conexão
    ligada: bool | None = None  # None = não sabe
    app: str | None = None  # id do apps.yaml se reconhecido, senão nome cru
    volume: int | None = None  # 0–100, só se a TV informa; nunca estimado
    mudo: bool | None = None
    entrada: str | None = None
    visto: datetime | None = None  # última resposta da TV


@dataclass(frozen=True, slots=True)
class Ola:
    tipo: TipoDispositivo
    versao: str  # versão do pacote (ex.: "0.9.0+ecf2c08")
    caps: tuple[str, ...] = ()  # pc: "turno","acao","evento","resumo"; casa: "acao","estado"
    retomar_desde: str | None = None  # último id de evento recebido
    tvs: tuple[TvInfo, ...] = ()  # só casa
    apps: tuple[AppInfo, ...] = ()  # só casa
    token: str | None = None  # só no elo local PC → casa (§10.2); a Ayanami recusa ola com token


@dataclass(frozen=True, slots=True)
class Bate:
    seq: int  # ≥ 0, crescente por conexão
    custos_mes_usd: float | None = None  # só o pc (§6.4)


@dataclass(frozen=True, slots=True)
class Turno:
    turno: str  # ULID do turno (também nos quadros binários)
    satelite: str = "celular"
    texto: str | None = None  # ≤ 4000 caracteres; exclusivo com audio
    audio: bool = False  # True → quadros AUDIO_IN seguem; fim = AUDIO_FIM
    dispositivo: str = ""


@dataclass(frozen=True, slots=True)
class CardElo:
    """Espelha ``CardMsg`` (``nivel`` = ``CardLevel``)."""

    titulo: str
    texto: str = ""
    url: str | None = None
    nivel: str = "info"


@dataclass(frozen=True, slots=True)
class TurnoFim:
    turno: str
    ok: bool
    texto: str = ""  # full_text ou speech; ≤ 16000 caracteres
    fala: str = ""
    cards: tuple[CardElo, ...] = ()
    expressao: str | None = None
    audio: bool = False  # True → houve AUDIO_OUT antes deste envelope
    erro: str | None = None  # código curto, nunca texto de exceção


@dataclass(frozen=True, slots=True)
class AcaoPedido:
    """``ActionRequest`` serializável (sem ``TurnContext``)."""

    intent: str
    slots: tuple[tuple[str, str], ...] = ()  # (SlotName, value)
    texto: str = ""
    confirmed: bool = False
    args: Mapping[str, str | int | float | bool] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Acao:
    pedido: AcaoPedido
    origem: str  # "voz-pc" | "pwa" | "mcp" | "nuvem"
    prazo_ms: int = 8000  # 500..30000


@dataclass(frozen=True, slots=True)
class AcaoResultado:
    ok: bool
    fala: str = ""
    motivo: str | None = None  # valor de Motivo (§10.5)
    precisa_confirmar: bool = False  # on_confirm não viaja: reenvia com confirmed=True
    perigosa: bool = False
    dados: Mapping[str, Any] = field(default_factory=dict)  # ≤ 4 KiB


@dataclass(frozen=True, slots=True)
class AcaoOk:
    resultado: AcaoResultado


@dataclass(frozen=True, slots=True)
class Estado:
    tvs: tuple[EstadoTv, ...] = ()  # ≤ 16; vazio só no elo local = "me manda o estado"


class EventoTipo(StrEnum):
    TAREFA_PRONTA = "tarefa_pronta"
    TAREFA_FALHOU = "tarefa_falhou"
    MONITOR = "monitor"
    LEMBRETE = "lembrete"
    NOTICIA_BOMBA = "noticia_bomba"
    BACKUP_FALHOU = "backup_falhou"
    CONFIRMACAO = "confirmacao"
    DISPOSITIVO = "dispositivo"


@dataclass(frozen=True, slots=True)
class Evento:
    seq: int  # eventos.id (§3)
    tipo: EventoTipo
    titulo: str  # ≤ 80 caracteres, sem dado sensível
    resumo: str = ""  # ≤ 200 caracteres
    ref: str | None = None  # "tarefa:<uuid>", "confirma:<ulid>", "noticia:<uid>"
    proativo: bool = True


@dataclass(frozen=True, slots=True)
class Confirma:
    pedido: str  # ULID da confirmação
    descricao: str = ""
    origem: str = "mcp"
    expira_em: datetime | None = None  # pergunta: agora + 120 s
    resposta: bool | None = None  # só na resposta


@dataclass(frozen=True, slots=True)
class TurnoNuvem:
    uid: str  # uuid de nuvem_turnos
    ts: datetime
    dispositivo: str
    texto_usuario: str
    texto_resposta: str
    ferramentas: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResumoNuvem:
    turnos: tuple[TurnoNuvem, ...]  # 1..50 por envelope
    restam: int = 0


@dataclass(frozen=True, slots=True)
class Ack:
    ids: tuple[str, ...] = ()  # resumo_nuvem: uids gravados; demais: vazio (vale o resp)


@dataclass(frozen=True, slots=True)
class Erro:
    codigo: str  # "invalido","nao_autorizado","escopo","offline","tempo","interno"
    msg: str = ""  # ≤ 200 caracteres, sem segredo


Corpo = Ola | Bate | Turno | TurnoFim | Acao | AcaoOk | Estado | Evento | Confirma | ResumoNuvem | Ack | Erro

CORPOS: Final[Mapping[Tipo, type]] = types.MappingProxyType(
    {
        Tipo.OLA: Ola,
        Tipo.BATE: Bate,
        Tipo.TURNO: Turno,
        Tipo.TURNO_FIM: TurnoFim,
        Tipo.ACAO: Acao,
        Tipo.ACAO_OK: AcaoOk,
        Tipo.ESTADO: Estado,
        Tipo.EVENTO: Evento,
        Tipo.CONFIRMA: Confirma,
        Tipo.RESUMO_NUVEM: ResumoNuvem,
        Tipo.ACK: Ack,
        Tipo.ERRO: Erro,
    }
)


# ---------------------------------------------------------------------------------------------
# Envelope (§1.1)
# ---------------------------------------------------------------------------------------------


def _checa_nome(caminho: str, nome: object) -> None:
    if not isinstance(nome, str) or NOME_RE.fullmatch(nome) is None:
        raise EloError("nome", f"{caminho}: nome inválido {nome!r}")


@dataclass(frozen=True, slots=True)
class Envelope:
    """Uma mensagem do elo. Validada na construção (§1.3); ``ts`` vira UTC truncado em ms."""

    t: Tipo
    corpo: Corpo  # coerente com ``t``
    de: str  # NOME_RE ("ayanami" incluso)
    para: str  # NOME_RE, "ayanami", ou o tipo "pc"/"casa" (roteado ao online)
    id: str = field(default_factory=novo_id)
    ts: datetime = field(default_factory=agora_utc)
    resp: str | None = None  # id do envelope que este responde
    v: int = VERSAO

    def __post_init__(self) -> None:
        if self.v != VERSAO:
            raise EloError("versao", f"v={self.v!r}")
        if not isinstance(self.t, Tipo):
            raise EloError("tipo", f"t={self.t!r}")
        esperado = CORPOS[self.t]
        if type(self.corpo) is not esperado:
            raise EloError("campo", f"corpo de {self.t.value} precisa ser {esperado.__name__}")
        _checa_nome("de", self.de)
        _checa_nome("para", self.para)
        if not valido(self.id):
            raise EloError("campo", f"id não é ULID: {self.id!r}")
        if self.resp is not None and not valido(self.resp):
            raise EloError("campo", f"resp não é ULID: {self.resp!r}")
        if not isinstance(self.ts, datetime) or self.ts.tzinfo is None:
            raise EloError("campo", "ts sem fuso")
        object.__setattr__(self, "ts", _trunca_ms(self.ts))
        _checa_corpo(self.corpo)

    @property
    def pede_resposta(self) -> bool:
        """``True`` se o emissor espera resposta (e reenvia o mesmo ``id``)."""
        return self.t in PEDE_RESPOSTA and not (self.t is Tipo.CONFIRMA and self.resp is not None)


def _excede(campo: str, texto: str | None, limite: int) -> None:
    if texto is not None and len(texto) > limite:
        raise EloError("tamanho", f"{campo}: {len(texto)} > {limite} caracteres")


def _checa_corpo(c: object) -> None:
    """Limites e regras de cada corpo (§1.2). Tamanho → ``"tamanho"``; o resto → ``"campo"``."""
    match c:
        case Bate(seq=seq) if seq < 0:
            raise EloError("campo", "bate.seq < 0")
        case Turno():
            if not valido(c.turno):
                raise EloError("campo", "turno.turno não é ULID")
            _excede("turno.texto", c.texto, MAX_TURNO_TEXTO)
            if c.texto is not None and c.audio:
                raise EloError("campo", "turno: texto e audio são exclusivos")
        case TurnoFim():
            if not valido(c.turno):
                raise EloError("campo", "turno_fim.turno não é ULID")
            _excede("turno_fim.texto", c.texto, MAX_TURNO_FIM_TEXTO)
        case Acao():
            if not PRAZO_MIN_MS <= c.prazo_ms <= PRAZO_MAX_MS:
                raise EloError("campo", f"acao.prazo_ms fora de {PRAZO_MIN_MS}..{PRAZO_MAX_MS}")
        case AcaoOk():
            dados = json.dumps(_para_json(c.resultado.dados), ensure_ascii=False, separators=(",", ":"))
            if len(dados.encode()) > MAX_DADOS_BYTES:
                raise EloError("tamanho", "acao_ok.resultado.dados > 4 KiB")
        case Estado():
            if len(c.tvs) > MAX_TVS:
                raise EloError("tamanho", f"estado.tvs > {MAX_TVS}")
            for tv in c.tvs:
                if tv.volume is not None and not 0 <= tv.volume <= 100:
                    raise EloError("campo", "estado.tvs.volume fora de 0..100")
        case Evento():
            if c.seq < 0:
                raise EloError("campo", "evento.seq < 0")
            _excede("evento.titulo", c.titulo, MAX_EVENTO_TITULO)
            _excede("evento.resumo", c.resumo, MAX_EVENTO_RESUMO)
        case Confirma() if not valido(c.pedido):
            raise EloError("campo", "confirma.pedido não é ULID")
        case ResumoNuvem():
            if len(c.turnos) > MAX_RESUMO_TURNOS:
                raise EloError("tamanho", f"resumo_nuvem.turnos > {MAX_RESUMO_TURNOS}")
            if not c.turnos:
                raise EloError("campo", "resumo_nuvem.turnos vazio")
            if c.restam < 0:
                raise EloError("campo", "resumo_nuvem.restam < 0")
        case Erro():
            _excede("erro.msg", c.msg, MAX_ERRO_MSG)
        case _:
            pass


# ---------------------------------------------------------------------------------------------
# Serialização
# ---------------------------------------------------------------------------------------------


def _para_json(v: Any) -> Any:
    if dataclasses.is_dataclass(v) and not isinstance(v, type):
        return {f.name: _para_json(getattr(v, f.name)) for f in dataclasses.fields(v)}
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, datetime):
        return formata_ts(v)
    if isinstance(v, tuple | list):
        return [_para_json(x) for x in v]
    if isinstance(v, Mapping):
        return {str(k): _para_json(x) for k, x in v.items()}
    return v


_DICAS: dict[type, dict[str, Any]] = {}


def _dicas(cls: type) -> dict[str, Any]:
    d = _DICAS.get(cls)
    if d is None:
        d = _DICAS[cls] = typing.get_type_hints(cls)
    return d


def _de_json(tp: Any, v: Any, caminho: str) -> Any:  # noqa: PLR0911, PLR0912
    """Valor JSON → valor do tipo ``tp``. Tipo errado → ``EloError("campo")``."""
    if tp is Any:
        return v
    origem = typing.get_origin(tp)
    if origem is typing.Union or origem is types.UnionType:
        args = typing.get_args(tp)
        if v is None:
            if type(None) in args:
                return None
            raise EloError("campo", f"{caminho}: nulo não permitido")
        for a in args:
            if a is type(None):
                continue
            try:
                return _de_json(a, v, caminho)
            except EloError:
                continue
        raise EloError("campo", f"{caminho}: tipo errado")
    if origem is tuple:
        if not isinstance(v, list):
            raise EloError("campo", f"{caminho}: esperado lista")
        args = typing.get_args(tp)
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_de_json(args[0], x, f"{caminho}[{i}]") for i, x in enumerate(v))
        if len(v) != len(args):
            raise EloError("campo", f"{caminho}: esperado {len(args)} itens")
        return tuple(_de_json(a, x, f"{caminho}[{i}]") for i, (a, x) in enumerate(zip(args, v, strict=True)))
    if origem is Mapping or origem is dict:
        if not isinstance(v, dict):
            raise EloError("campo", f"{caminho}: esperado objeto")
        vt = typing.get_args(tp)[1]
        return {k: _de_json(vt, x, f"{caminho}.{k}") for k, x in v.items()}
    if tp is bool:
        if not isinstance(v, bool):
            raise EloError("campo", f"{caminho}: esperado booleano")
        return v
    if tp is int:
        if not isinstance(v, int) or isinstance(v, bool):
            raise EloError("campo", f"{caminho}: esperado inteiro")
        return v
    if tp is float:
        if not isinstance(v, int | float) or isinstance(v, bool):
            raise EloError("campo", f"{caminho}: esperado número")
        return float(v)
    if tp is str:
        if not isinstance(v, str):
            raise EloError("campo", f"{caminho}: esperado texto")
        return v
    if tp is datetime:
        return le_ts(v, caminho)
    if isinstance(tp, type) and issubclass(tp, Enum):
        try:
            return tp(v)
        except ValueError as e:
            raise EloError("campo", f"{caminho}: valor fora de {tp.__name__}") from e
    if isinstance(tp, type) and dataclasses.is_dataclass(tp):
        return _de_dataclass(tp, v, caminho)
    raise EloError("campo", f"{caminho}: tipo não suportado {tp!r}")  # pragma: no cover


def _de_dataclass(cls: type, v: Any, caminho: str) -> Any:
    if not isinstance(v, dict):
        raise EloError("campo", f"{caminho}: esperado objeto")
    dicas = _dicas(cls)
    kwargs: dict[str, Any] = {}
    for f in dataclasses.fields(cls):
        if f.name in v:
            kwargs[f.name] = _de_json(dicas[f.name], v[f.name], f"{caminho}.{f.name}")
        elif f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING:
            raise EloError("campo", f"{caminho}.{f.name}: obrigatório")
    return cls(**kwargs)


def encode(env: Envelope) -> str:
    """JSON compacto (``ensure_ascii=False``). Acima de ``MAX_TEXTO_BYTES`` → ``EloError("tamanho")``."""
    d: dict[str, Any] = {
        "v": env.v,
        "t": env.t.value,
        "id": env.id,
        "de": env.de,
        "para": env.para,
        "ts": formata_ts(env.ts),
        "resp": env.resp,
        "corpo": _para_json(env.corpo),
    }
    s = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
    if len(s.encode()) > MAX_TEXTO_BYTES:
        raise EloError("tamanho", f"envelope > {MAX_TEXTO_BYTES} bytes")
    return s


def decode(raw: str | bytes) -> Envelope:
    """Texto/bytes JSON → ``Envelope`` validado (§1.3). Qualquer falha → ``EloError``."""
    tam = len(raw) if isinstance(raw, bytes) else len(raw.encode())
    if tam > MAX_TEXTO_BYTES:
        raise EloError("tamanho", f"envelope > {MAX_TEXTO_BYTES} bytes")
    try:
        d = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as e:
        raise EloError("json", "JSON inválido") from e
    if not isinstance(d, dict):
        raise EloError("json", "envelope precisa ser objeto")
    v = d.get("v")
    if v != VERSAO or isinstance(v, bool):
        raise EloError("versao", f"v={v!r}")
    try:
        t = Tipo(d.get("t"))
    except ValueError as e:
        raise EloError("tipo", f"t={d.get('t')!r}") from e
    for chave in ("id", "de", "para", "ts", "corpo"):
        if chave not in d:
            raise EloError("campo", f"{chave}: obrigatório")
    for chave in ("de", "para"):
        _checa_nome(chave, d[chave])
    if not valido(d["id"]):
        raise EloError("campo", "id não é ULID")
    resp = d.get("resp")
    if resp is not None and not valido(resp):
        raise EloError("campo", "resp não é ULID")
    try:
        corpo = _de_dataclass(CORPOS[t], d["corpo"], "corpo")
        return Envelope(
            t=t, corpo=corpo, de=d["de"], para=d["para"], id=d["id"], ts=le_ts(d["ts"]), resp=resp
        )
    except EloError:
        raise
    except (TypeError, ValueError) as e:  # pragma: no cover - defesa: nunca corpo parcial
        raise EloError("campo", str(e)) from e


def responder(env: Envelope, t: Tipo, corpo: Corpo, de: str) -> Envelope:
    """Resposta a ``env``: ``para=env.de``, ``resp=env.id``."""
    return Envelope(t=t, corpo=corpo, de=de, para=env.de, resp=env.id)
