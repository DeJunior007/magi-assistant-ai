"""Detector `det_sistema` (spec §5): 35, 37–41, 48, 80, 84, I4–I6.
Dono: R1.3.

34 (`hot`), 36 (`fps_drop`), 42 (`cleanup`), 44 (`game_on`) e 45 (`game_off`) já saem do
``Reactor._legado`` pelo ``fire`` antigo; aqui eles só são **espelhados** (mesmos limiares de
``reactions.py``) para alimentar as variantes novas (alívio, FPS recuperou, vergonha, eu avisei,
partida sem tropeço). Nenhum ``Disparo`` das chaves antigas sem variante sai daqui.

Estado entre ticks, só em chaves ``_sistema_*`` do ``ctx``:
``_sistema_acordou`` (48 já saiu; não sai com jogo aberto no 1º snapshot),
``_sistema_quente`` (histerese 85/78 °C; alívio só após ≥ 60 s quente),
``_sistema_hot_em`` (monotônico do último 34), ``_sistema_avisei`` (84 já saiu p/ esse 34),
``_sistema_fps_baixo`` (leituras seguidas abaixo de 60% da média), ``_sistema_fps_bom``
(leituras seguidas boas depois de uma queda), ``_sistema_caiu_fps`` (queda aberta),
``_sistema_quedas`` (quedas na sessão de jogo), ``_sistema_jogo_desde``, ``_sistema_tropeco``
(I6 já saiu ou houve queda), ``_sistema_teve_ip``, ``_sistema_sem_ip_desde``,
``_sistema_rede_caiu``, ``_sistema_pesado_desde``, ``_sistema_pesado`` (≥ 60 s acima de 5 MB/s),
``_sistema_disco``, ``_sistema_cpu_desde``, ``_sistema_cpu`` (80 já saiu no episódio),
``_sistema_swap`` (amostras ``(agora, GB)`` dos últimos 60 s), ``_sistema_sufoco``.
"""

from __future__ import annotations

from typing import Any

from .contratos import Disparo

HOT_C, COOL_C = 85.0, 78.0  # = reactions.HOT_C/COOL_C
FPS_DROP = 0.6  # = reactions.FPS_DROP (2 leituras seguidas)
FPS_OK = 0.9  # FPS recuperou: ≥ 90% da média por 2 leituras seguidas
ALIVIO_S = 60.0  # 35: só depois de ≥ 60 s quente (pico curto não vira alívio)
AVISEI_S = 600.0  # 84: hot/fps_drop até 10 min depois do 34
VERGONHA_N = 3  # I4: 3ª queda na mesma sessão de jogo
TROPECO_S = 30 * 60.0  # I6: 30 min de jogo sem queda
SEM_IP_S = 10.0  # 38
PESADO_BPS, PESADO_S, CALMO_BPS = 5_000_000.0, 60.0, 100_000.0  # 40
DISCO_CHEIO, DISCO_OK = 90.0, 85.0  # 41 (histerese)
CPU_ALTA, CPU_OK, CPU_S = 90.0, 80.0, 60.0  # 80
RAM_ALTA, RAM_OK, SWAP_GB, SWAP_S = 90.0, 85.0, 1.0, 60.0  # I5


def _quente(snap: Any, era: bool) -> bool:
    temps = [x for x in (snap.cpu_temp, snap.gpu_temp) if x is not None]
    return bool(temps) and max(temps) >= (COOL_C if era else HOT_C)


def detectar(anterior: Any, snap: Any, ctx: dict) -> list[Disparo]:
    """Compara o Snapshot ``anterior`` com ``snap`` e devolve os disparos deste tick."""
    if snap is None:
        return []
    agora = float(ctx.get("agora", 0.0))
    out: list[Disparo] = []

    # 48 · HUD acordou: primeiro snapshot da execução (com jogo aberto o palco é do game_on)
    if not ctx.get("_sistema_acordou"):
        ctx["_sistema_acordou"] = True
        if not snap.gaming:
            out.append(Disparo("hud_acordou", "primeiro snapshot"))

    _temperatura(snap, ctx, agora, out)
    _fps(anterior, snap, ctx, agora, out)
    _rede(snap, ctx, agora, out)
    _disco(snap, ctx, out)
    _cpu(snap, ctx, agora, out)
    _sufoco(snap, ctx, agora, out)
    return out


def _avisei(ctx: dict, agora: float, out: list[Disparo], motivo: str) -> None:
    """84 · Eu avisei: hot/fps_drop ≤ 10 min depois de ela ter reagido ao 34 (1× por 34)."""
    em = ctx.get("_sistema_hot_em")
    if em is not None and not ctx.get("_sistema_avisei") and agora - em <= AVISEI_S:
        ctx["_sistema_avisei"] = True
        out.append(Disparo("eu_avisei", motivo))


def _temperatura(snap: Any, ctx: dict, agora: float, out: list[Disparo]) -> None:
    era = bool(ctx.get("_sistema_quente"))
    quente = _quente(snap, era)
    ctx["_sistema_quente"] = quente
    if quente and not era:  # 34 saiu pelo fire antigo
        _avisei(ctx, agora, out, "esquentou de novo")
        ctx["_sistema_hot_em"], ctx["_sistema_avisei"] = agora, False
    elif era and not quente and agora - ctx.get("_sistema_hot_em", agora) >= ALIVIO_S:  # 35
        out.append(Disparo("hot", "abaixo de 78 °C", variante="alivio"))


def _fps(anterior: Any, snap: Any, ctx: dict, agora: float, out: list[Disparo]) -> None:
    jogo = bool(snap.gaming)
    if jogo and ctx.get("_sistema_jogo_desde") is None:  # sessão de jogo nova
        ctx["_sistema_jogo_desde"] = agora
        ctx["_sistema_quedas"], ctx["_sistema_tropeco"] = 0, False
    elif not jogo:
        ctx["_sistema_jogo_desde"] = None

    fps, media = snap.fps, snap.fps_avg
    if fps is not None and media and fps < FPS_DROP * media:
        ctx["_sistema_fps_baixo"] = ctx.get("_sistema_fps_baixo", 0) + 1
        ctx["_sistema_fps_bom"] = 0
        if ctx["_sistema_fps_baixo"] == 2:  # 36 saiu pelo fire antigo
            ctx["_sistema_caiu_fps"] = True
            ctx["_sistema_tropeco"] = True
            ctx["_sistema_quedas"] = ctx.get("_sistema_quedas", 0) + 1
            _avisei(ctx, agora, out, "fps caiu depois do calor")
            if jogo and ctx["_sistema_quedas"] == VERGONHA_N:  # I4
                out.append(Disparo("fps_drop", "3ª queda na sessão", variante="vergonha"))
    else:
        ctx["_sistema_fps_baixo"] = 0
        if ctx.get("_sistema_caiu_fps") and fps is not None and media and fps >= FPS_OK * media:
            ctx["_sistema_fps_bom"] = ctx.get("_sistema_fps_bom", 0) + 1
            if ctx["_sistema_fps_bom"] >= 2:  # 37 · FPS recuperou
                ctx["_sistema_caiu_fps"], ctx["_sistema_fps_bom"] = False, 0
                out.append(Disparo("fps_drop", "fps voltou", variante="recuperou"))
        else:
            ctx["_sistema_fps_bom"] = 0

    desde = ctx.get("_sistema_jogo_desde")
    if jogo and desde is not None and not ctx.get("_sistema_tropeco") and agora - desde >= TROPECO_S:
        ctx["_sistema_tropeco"] = True  # I6 · 1×/sessão
        out.append(Disparo("sem_tropeco", "30 min sem queda de FPS"))


def _rede(snap: Any, ctx: dict, agora: float, out: list[Disparo]) -> None:
    if snap.net_ip:
        ctx["_sistema_teve_ip"], ctx["_sistema_sem_ip_desde"] = True, None
        if ctx.get("_sistema_rede_caiu"):  # 39 · volta da queda
            ctx["_sistema_rede_caiu"] = False
            out.append(Disparo("rede_voltou", "ip de volta"))
    elif ctx.get("_sistema_teve_ip"):  # 38 · só depois de ter tido rede nesta execução
        desde = ctx.get("_sistema_sem_ip_desde")
        if desde is None:
            ctx["_sistema_sem_ip_desde"] = desde = agora
        if not ctx.get("_sistema_rede_caiu") and agora - desde >= SEM_IP_S:
            ctx["_sistema_rede_caiu"] = True
            out.append(Disparo("rede_caiu", "sem ip há 10 s"))

    # 40 · ↓ ≥ 5 MB/s por ≥ 60 s e depois < 100 kB/s
    down = snap.net_down
    if down is None:
        return
    if down >= PESADO_BPS:
        if ctx.get("_sistema_pesado_desde") is None:
            ctx["_sistema_pesado_desde"] = agora
        if agora - ctx["_sistema_pesado_desde"] >= PESADO_S:
            ctx["_sistema_pesado"] = True
        return
    ctx["_sistema_pesado_desde"] = None
    if down < CALMO_BPS and ctx.get("_sistema_pesado"):
        ctx["_sistema_pesado"] = False
        out.append(Disparo("transferencia_acabou", "download pesado terminou"))


def _disco(snap: Any, ctx: dict, out: list[Disparo]) -> None:
    pct = snap.disk_pct
    if pct is None:
        return
    era = bool(ctx.get("_sistema_disco"))
    cheio = pct >= (DISCO_OK if era else DISCO_CHEIO)
    ctx["_sistema_disco"] = cheio
    if cheio and not era:  # 41
        out.append(Disparo("disco_cheio", f"disco em {pct:.0f}%", fmt={"pct": f"{pct:.0f}"}))


def _cpu(snap: Any, ctx: dict, agora: float, out: list[Disparo]) -> None:
    cpu = snap.cpu
    if cpu is None or snap.gaming or cpu < CPU_OK:
        ctx["_sistema_cpu_desde"], ctx["_sistema_cpu"] = None, False
        return
    if cpu < CPU_ALTA:  # entre 80 e 90: mantém o episódio, não conta tempo novo
        if not ctx.get("_sistema_cpu"):
            ctx["_sistema_cpu_desde"] = None
        return
    if ctx.get("_sistema_cpu_desde") is None:
        ctx["_sistema_cpu_desde"] = agora
    if not ctx.get("_sistema_cpu") and agora - ctx["_sistema_cpu_desde"] >= CPU_S:  # 80
        ctx["_sistema_cpu"] = True
        out.append(Disparo("impaciente", "cpu ≥ 90% há 60 s"))


def _sufoco(snap: Any, ctx: dict, agora: float, out: list[Disparo]) -> None:
    """I5 · RAM ≥ 90% ou swap +1 GB em 60 s (1× por episódio; sai com RAM < 85% e swap parado)."""
    amostras = [(t, g) for t, g in ctx.get("_sistema_swap", []) if agora - t <= SWAP_S]
    if snap.swap_used_gb is not None:
        amostras.append((agora, float(snap.swap_used_gb)))
    ctx["_sistema_swap"] = amostras
    swap_subiu = bool(amostras) and amostras[-1][1] - min(g for _, g in amostras) >= SWAP_GB
    ram = snap.ram
    if (ram is not None and ram >= RAM_ALTA) or swap_subiu:
        if not ctx.get("_sistema_sufoco"):
            ctx["_sistema_sufoco"] = True
            out.append(Disparo("sufocando", "ram cheia" if not swap_subiu else "swap subiu 1 GB"))
    elif ram is None or ram < RAM_OK:
        ctx["_sistema_sufoco"] = False
