"""Governador (spec §3): cotas, cooldown, prioridade, fila, bloqueios, blush/lágrima, Ado e as
desligadas do Pedro. Puro, relógio injetado (``agora`` em segundos). Dono: R0.2; v2: V0.5.

``escolher`` é o caminho das reações antigas (até o diretor da V0.10 passar todas pelo
``Governador`` v2, mais abaixo, spec §5–§6 de specs/condessa-vida). O intervalo das passivas e o teto
de ativas vêm do ``[vida]`` (``ctx["vida"]``; padrão ``VIDA_PADRAO``).

``ctx`` (dict) — chaves lidas, todas opcionais salvo ``defs``:

- ``defs``: catálogo, ``{chave: Def}`` ou ``{(chave, variante): Def}`` (variante tenta primeiro);
- ``estado``: ``Estado`` com o histórico (criado em ``ctx`` se faltar; guarde o ``ctx`` entre ticks);
- ``hora``: hora local 0–23 (padrão: ``time.localtime(agora)``);
- ``humor``: humor do Pedro (0–5; padrão 3); ``jogo``, ``claude``: bool; ``musica_nota``: int;
- ``ado``: bool (faixa tocando é da Ado); ``desligadas``: chaves do ``[reacoes] desligadas``;
- ``parada``: Magui parada (padrão True). Não parada → só a fila (VOLTA/VITORIA) anda;
- ``vida``: o ``[vida]`` já mesclado (gosto + Pedro); chaves que faltarem vêm de ``VIDA_PADRAO``.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field, replace
from enum import StrEnum

from .contratos import Classe, Def, Disparo, Passo
from .vida import VIDA_PADRAO, Momento, mesclar

HORA_S = 3600.0
DIA_S = 86400.0
PASSIVA_MIN_S = float(VIDA_PADRAO["passiva_min_s"])  # o valor vivo vem de ctx["vida"]
ATIVAS_POR_HORA = int(VIDA_PADRAO["cenas_hora"])
FILA_VALIDADE_S = 30.0
BLUSH_POR_HORA = 1
BLUSH_LIVRE = frozenset({62, 74, 87})  # Nº fora da conta do blush e nunca barrados
FURAM_COTA = frozenset({Classe.SISTEMA, Classe.VITORIA, Classe.VOLTA})
FILA_CLASSES = frozenset({Classe.VOLTA, Classe.VITORIA})
RANK = {Classe.SISTEMA: 5, Classe.PEDRO: 4, Classe.MUSICA: 3, Classe.TEMPO: 2, Classe.PASSIVA: 1}
COBRANCA_BOCAS = frozenset({"C8", "C11"})
COBRANCA_TROCA = "C9"


@dataclass
class Estado:
    """Histórico do governador (tempos em segundos do relógio injetado)."""

    toques: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    passivas: list[float] = field(default_factory=list)
    ativas: list[float] = field(default_factory=list)  # só as que contam no teto
    blush: list[float] = field(default_factory=list)  # só as que contam
    lagrima: list[float] = field(default_factory=list)
    fila: tuple[Def, Disparo, float] | None = None
    ultimo: Disparo | None = None  # disparo da última reação aprovada (para o registro)
    lagrima_liberada: str | None = None  # chave aprovada com lágrima de verdade

    def podar(self, agora: float) -> None:
        corte = agora - DIA_S
        for k in list(self.toques):
            self.toques[k] = [t for t in self.toques[k] if t > corte]
            if not self.toques[k]:
                del self.toques[k]
        self.passivas = [t for t in self.passivas if t > agora - HORA_S]
        self.ativas = [t for t in self.ativas if t > agora - HORA_S]
        self.blush = [t for t in self.blush if t > agora - HORA_S]
        self.lagrima = [t for t in self.lagrima if t > corte]


def noite(hora: int) -> bool:
    """22h–04h (inclui a hora 4)."""
    return hora >= 22 or hora <= 4


def tem_efeito(d: Def, nome: str) -> bool:
    return any(nome in p.efeitos for p in d.passos)


def furou_cota(d: Def) -> bool:
    """Reação que não conta nem é barrada pelo teto de ativas."""
    return bool(d.classes & FURAM_COTA)


def _passiva(d: Def) -> bool:
    return Classe.PASSIVA in d.classes


def _hora(agora: float, ctx: dict) -> int:
    h = ctx.get("hora")
    return int(h) if h is not None else time.localtime(agora).tm_hour


def _estado(ctx: dict) -> Estado:
    est = ctx.get("estado")
    if est is None:
        est = ctx["estado"] = Estado()
    return est


def _achar(disp: Disparo, defs: dict) -> Def | None:
    if disp.variante is not None and (disp.chave, disp.variante) in defs:
        return defs[(disp.chave, disp.variante)]
    return defs.get(disp.chave)


def _rank(d: Def) -> tuple[int, int]:
    return (max((RANK.get(c, 0) for c in d.classes), default=0), d.prio)


def _contexto_ok(d: Def, ctx: dict, hora: int) -> bool:
    """Bloqueios de contexto (R3, R11, Ado)."""
    if d.chave in set(ctx.get("desligadas") or ()):
        return False
    humor = ctx.get("humor", 3)
    if Classe.ZOEIRA in d.classes and (humor <= 1 or noite(hora)):
        return False
    if Classe.SONO in d.classes and (
        ctx.get("jogo") or ctx.get("claude") or ctx.get("musica_nota", 0) >= 1
    ):
        return False
    if Classe.RARA in d.classes and ctx.get("jogo"):
        return False
    return not (ctx.get("ado") and (tem_efeito(d, "blush") or d.mood == "love"))


def _vida(ctx: dict) -> dict:
    v = ctx.get("vida")
    return VIDA_PADRAO if not v else {**VIDA_PADRAO, **v}


def _cota_ok(d: Def, agora: float, est: Estado, ctx: dict | None = None) -> bool:
    """Cotas e cooldowns (R2), com o histórico já podado."""
    vida = _vida(ctx or {})
    toques = est.toques.get(d.chave, ())
    if _passiva(d) and est.passivas and agora - est.passivas[-1] < vida["passiva_min_s"]:
        return False
    if Classe.RARA in d.classes and any(agora - t < HORA_S for t in toques):
        return False
    if Classe.DIARIA in d.classes and toques:
        return False
    if not _passiva(d):
        if toques and agora - toques[-1] < d.cooldown_s:
            return False
        if not furou_cota(d) and len(est.ativas) >= vida["cenas_hora"]:
            return False
    return not (
        tem_efeito(d, "blush") and d.n not in BLUSH_LIVRE and len(est.blush) >= BLUSH_POR_HORA
    )


def _aprovar(d: Def, disp: Disparo, agora: float, hora: int, est: Estado) -> Def:
    est.toques[d.chave].append(agora)
    if _passiva(d):
        est.passivas.append(agora)
    elif not furou_cota(d):
        est.ativas.append(agora)
    if tem_efeito(d, "blush") and d.n not in BLUSH_LIVRE:
        est.blush.append(agora)
    est.lagrima_liberada = None
    if tem_efeito(d, "tear") and noite(hora) and not est.lagrima:
        est.lagrima.append(agora)
        est.lagrima_liberada = d.chave
    est.ultimo = disp
    return d


def escolher(disparos: list[Disparo], agora: float, ctx: dict) -> Def | None:
    """No máximo 1 reação aprovada neste tick (ou a que estava na fila)."""
    est = _estado(ctx)
    est.podar(agora)
    hora = _hora(agora, ctx)
    defs = ctx.get("defs") or {}
    cands: list[tuple[Def, Disparo]] = []
    for disp in disparos:
        d = _achar(disp, defs)
        if d is not None and _contexto_ok(d, ctx, hora) and _cota_ok(d, agora, est, ctx):
            cands.append((d, disp))

    if est.fila is not None and agora - est.fila[2] > FILA_VALIDADE_S:
        est.fila = None

    if not ctx.get("parada", True):
        fila = [(d, disp) for d, disp in cands if d.classes & FILA_CLASSES]
        if fila:
            d, disp = max(fila, key=lambda c: _rank(c[0]))
            if est.fila is None or _rank(d) >= _rank(est.fila[0]):
                est.fila = (d, disp, agora)
        return None

    if est.fila is not None:
        d, disp, _ = est.fila
        est.fila = None
        if _contexto_ok(d, ctx, hora) and _cota_ok(d, agora, est, ctx):
            cands.append((d, disp))
    if not cands:
        return None
    d, disp = max(cands, key=lambda c: _rank(c[0]))
    return _aprovar(d, disp, agora, hora, est)


def aplicar_bloqueios(d: Def, ctx: dict) -> tuple[Passo, ...]:
    """Passos de ``d`` com os bloqueios aplicados (C8/C11 -> C9; tira ``tear`` fora de hora).

    Com ``estado`` no ``ctx``, a lágrima só fica se ``escolher`` a liberou (≤ 1/dia); sem ele,
    basta ser noite."""
    hora = _hora(time.time(), ctx) if ctx.get("hora") is None else int(ctx["hora"])
    cobrar = Classe.COBRANCA in d.classes and (ctx.get("humor", 3) <= 1 or noite(hora))
    est = ctx.get("estado")
    lagrima = noite(hora) and (est is None or est.lagrima_liberada == d.chave)
    passos = []
    for p in d.passos:
        if cobrar and p.mouth in COBRANCA_BOCAS:
            p = replace(p, mouth=COBRANCA_TROCA)
        if not lagrima and "tear" in p.efeitos:
            p = replace(p, efeitos=tuple(e for e in p.efeitos if e != "tear"))
        passos.append(p)
    return tuple(passos)


# ---------------------------------------------------------------------------------------------------
# Governador v2 (spec §5–§6, acordo §4). Números do ``[vida]``; janelas por tempo de parede (``agora``
# é o relógio de parede, em segundos), e os contadores saem/entram por ``exportar``/``importar`` para o
# ``Estado`` da vida persistir entre reinícios (CA-V2).


class Tipo(StrEnum):
    CENA = "cena"
    GESTO = "gesto"  # passiva
    ATIVA_SOLTA = "ativa_solta"
    ATENCAO = "atencao"  # olhada dirigida, fora de cota
    CORPO = "corpo"  # respirar, piscar, sway: fora de cota


EXPRESSOES = frozenset({Tipo.CENA, Tipo.GESTO, Tipo.ATIVA_SOLTA})
FURA_TUDO = frozenset({"pedro_fala", "clique_rosto", "pedro_volta", "rede_caiu", "disco_cheio"})
CAUSAS_NEGATIVAS = frozenset({
    "pulo_faixa_amada", "faixa_nota_menos1", "claude_demorando", "claude_esperando", "ignorada",
    "truque_ignorado", "episodio_jogo",
})
FAMILIA_MUSICA = "musica"
SEM_PISO = frozenset({Momento.CONVERSA, Momento.JOGANDO})


@dataclass(frozen=True)
class Pedido:
    """O que o diretor quer mostrar; o ``Governador`` diz se pode."""

    tipo: Tipo
    chave: str
    familia: str | None = None  # tipo de cena ("musica", "claude", ...): absorvida por 30 s / 90 s
    negativa: bool = False  # suspiro, franja, beicinho de birra
    causas: frozenset[str] = frozenset()  # causas que valem para esta negativa (vazio = todas)
    fura: str | None = None  # motivo de FURA_TUDO
    truque: bool = False


def causas_recentes(ctx: dict, agora: float) -> frozenset[str]:
    """Causas de negativa vistas há ≤ ``negativa_causa_s`` (``ctx["causas"]``: ``{nome: em}``)."""
    janela = _vida(ctx)["negativa_causa_s"]
    return frozenset(
        nome for nome, em in (ctx.get("causas") or {}).items()
        if nome in CAUSAS_NEGATIVAS and 0 <= agora - em <= janela
    )


class Governador:
    """Cotas e ritmo da vida. ``pode`` só consulta; ``aprovar`` consulta e registra."""

    def __init__(self, cfg: dict | None = None) -> None:
        self.cfg = mesclar(VIDA_PADRAO, cfg or {})
        # (em, tipo, chave, familia, negativa, truque) — só o que foi aprovado
        self.hist: list[tuple[float, str, str, str | None, bool, bool]] = []

    # -- contadores -------------------------------------------------------------------------------
    def podar(self, agora: float) -> None:
        """Esquece o que passou de 1 dia e o que está no futuro (relógio de parede voltou)."""
        self.hist = [h for h in self.hist if agora - DIA_S < h[0] <= agora]

    def exportar(self) -> dict:
        """Contadores serializáveis (JSON) para o ``Estado``."""
        return {"hist": [list(h) for h in self.hist]}

    def importar(self, dados: dict | None, agora: float | None = None) -> None:
        self.hist = [
            (float(h[0]), str(h[1]), str(h[2]), h[3], bool(h[4]), bool(h[5]))
            for h in (dados or {}).get("hist", ())
        ]
        self.hist.sort(key=lambda h: h[0])
        if agora is not None:
            self.podar(agora)

    def _ultimo(self, tipos: frozenset[str] | set[str]) -> float | None:
        return next((h[0] for h in reversed(self.hist) if h[1] in tipos), None)

    def _na_hora(self, agora: float, tipo: str | None = None, chave: str | None = None) -> int:
        return sum(
            1 for h in self.hist
            if agora - h[0] < HORA_S and (tipo is None or h[1] == tipo)
            and (chave is None or h[2] == chave)
        )

    def peso(self, chave: str, agora: float) -> float:
        """Peso de sorteio da mesma passiva: ×0,3 por uso na última hora."""
        return self.cfg["passiva_peso_por_uso"] ** self._na_hora(agora, Tipo.GESTO, chave)

    # -- regras -----------------------------------------------------------------------------------
    def motivo(self, p: Pedido, agora: float, ctx: dict | None = None) -> str | None:
        """``None`` se pode; senão o nome da regra que barrou."""
        ctx = ctx or {}
        c = self.cfg
        if p.fura is not None:
            return None if p.fura in FURA_TUDO else "fura_desconhecido"
        if p.tipo not in EXPRESSOES:
            return None  # ATENCAO e CORPO: fora de cota
        if p.negativa:
            if ctx.get("filtros"):
                return "negativa_sob_filtro"
            causas = causas_recentes({"vida": c, **ctx}, agora)
            if not (causas & p.causas if p.causas else causas):
                return "negativa_sem_causa"
            negs = sum(1 for h in self.hist if h[4] and agora - h[0] < HORA_S)
            if negs >= c["negativas_hora"]:
                return "negativas_hora"
        if p.truque and sum(1 for h in self.hist if h[5] and agora - h[0] < DIA_S) >= c["truque_dia"]:
            return "truque_dia"
        ult = self._ultimo(EXPRESSOES)
        if ult is not None and agora - ult < c["min_entre_expressoes_s"]:
            return "min_entre_expressoes"
        if p.tipo == Tipo.CENA:
            if self._na_hora(agora, Tipo.CENA) >= c["cenas_hora"]:
                return "cenas_hora"
            if p.familia is not None:
                janela = c["familia_musica_s"] if p.familia == FAMILIA_MUSICA else c["familia_absorve_s"]
                if any(h[1] == Tipo.CENA and h[3] == p.familia and agora - h[0] < janela
                       for h in self.hist):
                    return "mesma_familia"
        if p.tipo == Tipo.GESTO:
            cena = self._ultimo({Tipo.CENA})
            if cena is not None and agora - cena < c["pausa_apos_cena_s"]:
                return "pausa_apos_cena"
            gesto = self._ultimo({Tipo.GESTO})
            if gesto is not None and agora - gesto < c["passiva_min_s"]:
                return "passiva_min"
            if self._na_hora(agora, Tipo.GESTO) >= c["passivas_hora"]:
                return "passivas_hora"
        return None

    def pode(self, p: Pedido, agora: float, ctx: dict | None = None) -> bool:
        return self.motivo(p, agora, ctx) is None

    def registrar(self, p: Pedido, agora: float) -> None:
        if p.tipo == Tipo.CORPO:
            return
        self.hist.append((agora, str(p.tipo), p.chave, p.familia, p.negativa, p.truque))
        self.podar(agora)

    def aprovar(self, p: Pedido, agora: float, ctx: dict | None = None) -> bool:
        if not self.pode(p, agora, ctx):
            return False
        self.registrar(p, agora)
        return True

    def piso_vencido(self, agora: float, ctx: dict | None = None) -> bool:
        """Piso de vida: Pedro presente, fora de Conversa e de jogo, > 6 min sem expressão/atenção."""
        ctx = ctx or {}
        if not ctx.get("pedro_presente", True) or ctx.get("momento") in SEM_PISO:
            return False
        ult = self._ultimo(EXPRESSOES | {Tipo.ATENCAO})
        return ult is None or agora - ult > self.cfg["piso_vida_min"] * 60

