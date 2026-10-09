"""Detector `det_tempo` (spec §5): 17–20, 57–62, I1, I2, I16, I17, I19. Dono: R1.4.

Tempo, tédio e volta do Pedro. O ``Reactor`` ainda não chama ``atividade.evento``: os eventos
reais são deduzidos aqui da diferença ``anterior`` → ``snap`` (faixa nova ou música voltando a
tocar, Claude Code passou a rodar, Magui ouvindo, jogo abriu) e registrados em
``ctx["atividade"]`` com o relógio de parede (``ctx["relogio"]``).

Números (acordo §1/§2; os sem número no acordo estão marcados "escolha"):

- "quieto" = Magui parada (``sleeping``), Claude parado, sem música tocando e sem jogo;
- 17 bocejo: quieto ≥ 10 min; 18 cochilo: quieto ≥ 25 min (1× por trecho quieto cada);
- 19 cabeça pesada: sessão ≥ 2 h de madrugada (0h–4h), 1×/sessão. 17–19 nunca com jogo, Claude
  rodando ou música nota ≥ 1 (regra do sono);
- 20 sobressalto: evento real depois de um 18; 57 bom dia: 1º evento real do dia ≥ 05h;
  62 sentiu falta: evento real depois de ≥ 2 h sem nenhum. Só um por evento: 57 > 62 > 20;
- sessão = Pedro ativo (evento real < 30 min, Claude, música, jogo ou Magui fora de parada) sem
  buraco ≥ 30 min (escolha);
- 58 almoço: ativo entre 12h–13h59 (escolha), 1×/dia; 59 meia-noite: virada 23h → 0h ativo;
  60 madrugada pesada: ativo 3h–4h59, 1×/dia; 61 (``long_session``/``pausa``): sessão ≥ 2 h sem
  jogo (com jogo é o ``long_session`` antigo), 1×/sessão;
- I1: Claude rodando ≥ 2 h (buracos < 10 min não zeram, escolha) para 0 depois das 18h, 1×/dia;
- I2: 0h–4h, música parou há ≤ 30 min (escolha) e Claude parado ≥ 10 min, 1×/noite;
- I16: 0h–4h, quieto ≥ 30 min e nenhum evento real ≥ 30 min, 1×/noite;
- I17: 8h–22h59, sem música, sem jogo (escolha), Claude parado ≥ 40 min; 1 a cada 2 h;
- I19: dia/mês do 1º commit do repositório MAGI (``git`` lido 1× por processo; injetável por
  ``ctx["git"]`` — função sem argumentos que devolve ``AAAA-MM-DD`` ou None), com o Pedro ativo.

Chaves próprias no ``ctx``: ``_tempo_*``.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .atividade import dia_local
from .contratos import Disparo

MIN = 60.0
BOCEJO_S = 10 * MIN
COCHILO_S = 25 * MIN
AUSENTE_S = 2 * 3600.0
PAUSA_S = 30 * MIN
SESSAO_S = 2 * 3600.0
EXPEDIENTE_S = 2 * 3600.0
EXPEDIENTE_H = 18
CLAUDE_BURACO_S = 10 * MIN
BOA_NOITE_CLAUDE_S = 10 * MIN
BOA_NOITE_MUSICA_S = 30 * MIN
SILENCIO_S = 30 * MIN
EI_CLAUDE_S = 40 * MIN
EI_A_CADA_S = 2 * 3600.0
MADRUGADA_H = range(0, 5)
PESADA_H = range(3, 5)
ALMOCO_H = range(12, 14)
EI_H = range(8, 23)

REPO = Path(__file__).resolve().parents[3]


def git_primeiro_commit(repo: Path = REPO) -> str | None:
    """Data (``AAAA-MM-DD``) do primeiro commit de ``repo``; None se não der."""
    try:
        r = subprocess.run(
            ["git", "-C", str(repo), "log", "--reverse", "--format=%as"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    linhas = r.stdout.split()
    return linhas[0] if r.returncode == 0 and linhas else None


GIT: Callable[[], str | None] = git_primeiro_commit
_CACHE: dict[str, str | None] = {}  # data do 1º commit, lida uma vez por processo


def _aniversario(ctx: dict) -> str | None:
    """``MM-DD`` do 1º commit (cacheado no ``ctx``)."""
    if "_tempo_aniv" not in ctx:
        git = ctx.get("git")
        try:
            if git is not None:
                data = git()
            else:
                if "data" not in _CACHE:
                    _CACHE["data"] = GIT()
                data = _CACHE["data"]
        except Exception:  # noqa: BLE001 - sem git não há aniversário
            data = None
        ctx["_tempo_aniv"] = data[5:10] if isinstance(data, str) and len(data) >= 10 else None
    return ctx["_tempo_aniv"]


def _faixa(snap: Any) -> tuple | None:
    t = getattr(snap, "track", None)
    if t is None or not (t.title or t.artist):
        return None
    return (t.title, t.artist)


def _musica(snap: Any) -> bool:
    t = getattr(snap, "track", None)
    return t is not None and bool(t.playing) and _faixa(snap) is not None


def _claude(snap: Any) -> bool:
    c = getattr(snap, "claude", None)
    return bool(c is not None and getattr(c, "running", 0))


def _magui(snap: Any) -> str:
    return getattr(snap, "magui_state", "sleeping")


def _jogo(snap: Any) -> bool:
    return bool(getattr(snap, "gaming", False))


def eventos(anterior: Any, snap: Any) -> list[str]:
    """Eventos reais deduzidos de ``anterior`` → ``snap`` (nenhum no 1º snapshot)."""
    if anterior is None:
        return []
    ev = []
    if _musica(snap) and (_faixa(snap) != _faixa(anterior) or not _musica(anterior)):
        ev.append("faixa")
    if _claude(snap) and not _claude(anterior):
        ev.append("claude")
    if _magui(snap) == "listening" and _magui(anterior) != "listening":
        ev.append("magui")
    if _jogo(snap) and not _jogo(anterior):
        ev.append("jogo")
    return ev


def _uma_vez(ctx: dict, nome: str, chave: str) -> bool:
    """Verdadeiro na 1ª vez de ``nome`` com ``chave`` (dia, sessão…); marca."""
    feito = ctx.setdefault("_tempo_feito", {})
    if feito.get(nome) == chave:
        return False
    feito[nome] = chave
    return True


def _volta(anterior: Any, snap: Any, ctx: dict, relogio: float) -> list[Disparo]:
    ativ = ctx.get("atividade")
    evs = eventos(anterior, snap)
    if not evs or ativ is None:
        return []
    parado = ativ.parado_s(relogio)
    primeiro = ativ.evento(relogio, evs[0])
    cochilou = ctx.pop("_tempo_cochilou", False)
    motivo = "+".join(evs)
    if primeiro:
        return [Disparo("bom_dia", f"1º evento do dia ({motivo})")]
    if parado is not None and parado >= AUSENTE_S:
        return [Disparo("sentiu_falta", f"voltou depois de {parado / 3600:.1f} h ({motivo})")]
    if cochilou:
        return [Disparo("sobressalto", f"acordou do cochilo ({motivo})")]
    return []


def _claude_ponto(ctx: dict, claude: bool, agora: float, hora: int, hoje: str) -> list[Disparo]:
    """Atualiza ``_tempo_claude_on``/``_tempo_claude_off``; I1 na parada depois de ≥ 2 h."""
    out = []
    on, off = ctx.get("_tempo_claude_on"), ctx.get("_tempo_claude_off")
    if claude:
        if on is None or (off is not None and agora - off >= CLAUDE_BURACO_S):
            ctx["_tempo_claude_on"] = agora
        ctx["_tempo_claude_off"] = None
    elif off is None:
        ctx["_tempo_claude_off"] = agora
        if (on is not None and agora - on >= EXPEDIENTE_S and hora >= EXPEDIENTE_H
                and _uma_vez(ctx, "I1", hoje)):
            out.append(Disparo("fim_expediente", f"Claude parou depois de {(agora - on) / 3600:.1f} h"))
    return out


def detectar(anterior: Any, snap: Any, ctx: dict) -> list[Disparo]:
    """Compara o Snapshot ``anterior`` com ``snap`` e devolve os disparos deste tick."""
    if snap is None:
        return []
    agora = float(ctx.get("agora", 0.0))
    relogio = ctx.get("relogio")
    relogio = float(relogio) if relogio is not None else time.time()
    hora = ctx.get("hora")
    hora = int(hora) if hora is not None else time.localtime(relogio).tm_hour
    hoje = dia_local(relogio)
    claude, musica = _claude(snap), _musica(snap)
    jogo = _jogo(snap) or bool(ctx.get("jogo"))
    nota = ctx.get("musica_nota") or 0
    sono_ok = not jogo and not claude and nota < 1
    madrugada = hora in MADRUGADA_H

    out = _volta(anterior, snap, ctx, relogio)
    out += _claude_ponto(ctx, claude, agora, hora, hoje)
    claude_off = ctx.get("_tempo_claude_off")
    claude_parado_s = agora - claude_off if claude_off is not None else 0.0

    ativ = ctx.get("atividade")
    parado = ativ.parado_s(relogio) if ativ is not None else None
    recente = parado is not None and parado < PAUSA_S
    ativo = recente or claude or musica or jogo or _magui(snap) != "sleeping"

    # sessão (buraco ≥ 30 min começa outra)
    if ativo:
        ult = ctx.get("_tempo_ativo_em")
        if ult is None or agora - ult >= PAUSA_S:
            ctx["_tempo_sessao"] = agora
        ctx["_tempo_ativo_em"] = agora
    sessao = agora - ctx["_tempo_sessao"] if ativo and "_tempo_sessao" in ctx else 0.0
    sessao_id = str(ctx.get("_tempo_sessao"))

    # trecho quieto: 17, 18, I16
    quieto = _magui(snap) == "sleeping" and not claude and not musica and not jogo
    if quieto:
        quieto_s = agora - ctx.setdefault("_tempo_quieto", agora)
    else:
        ctx.pop("_tempo_quieto", None)
        quieto_s = 0.0
    trecho = str(ctx.get("_tempo_quieto"))
    if quieto and sono_ok:
        if quieto_s >= BOCEJO_S and _uma_vez(ctx, "17", trecho):
            out.append(Disparo("bocejo", f"quieta há {quieto_s / MIN:.0f} min"))
        if quieto_s >= COCHILO_S and _uma_vez(ctx, "18", trecho):
            ctx["_tempo_cochilou"] = True
            out.append(Disparo("cochilo", f"quieta há {quieto_s / MIN:.0f} min"))
    if (madrugada and quieto and quieto_s >= SILENCIO_S and (parado is None or parado >= SILENCIO_S)
            and _uma_vez(ctx, "I16", hoje)):
        out.append(Disparo("silencio_longo", "madrugada em silêncio"))

    # sessão longa: 19, 61
    if madrugada and sono_ok and sessao >= SESSAO_S and _uma_vez(ctx, "19", sessao_id):
        out.append(Disparo("cabeca_pesada", f"sessão de {sessao / 3600:.1f} h de madrugada"))
    if not jogo and sessao >= SESSAO_S and _uma_vez(ctx, "61", sessao_id):
        out.append(Disparo("long_session", f"sessão de {sessao / 3600:.1f} h sem pausa", "pausa"))

    # horários: 58, 59, 60
    hora_ant = ctx.get("_tempo_hora")
    ctx["_tempo_hora"] = hora
    if ativo and hora in ALMOCO_H and _uma_vez(ctx, "58", hoje):
        out.append(Disparo("almoco", "hora do almoço"))
    if ativo and hora_ant == 23 and hora == 0:
        out.append(Disparo("meia_noite", "virada para 00:00"))
    if ativo and hora in PESADA_H and _uma_vez(ctx, "60", hoje):
        out.append(Disparo("madrugada", f"usando o PC às {hora}h"))

    # I2: música parou de madrugada com Claude parado
    if musica:
        ctx.pop("_tempo_musica_parou", None)
    elif anterior is not None and _musica(anterior):
        ctx["_tempo_musica_parou"] = agora
    parou = ctx.get("_tempo_musica_parou")
    if (madrugada and not musica and parou is not None and agora - parou <= BOA_NOITE_MUSICA_S
            and not claude and claude_parado_s >= BOA_NOITE_CLAUDE_S and _uma_vez(ctx, "I2", hoje)):
        out.append(Disparo("boa_noite", "música parou e Claude parado de madrugada"))

    # I17: tédio de dia
    ei = ctx.get("_tempo_ei_em")
    if (hora in EI_H and not musica and not jogo and not claude and claude_parado_s >= EI_CLAUDE_S
            and (ei is None or agora - ei >= EI_A_CADA_S)):
        ctx["_tempo_ei_em"] = agora
        out.append(Disparo("ei_to_aqui", f"Claude parado há {claude_parado_s / MIN:.0f} min"))

    # I19: aniversário dela
    if ativo and hora >= 5 and _uma_vez(ctx, "I19", hoje) and _aniversario(ctx) == hoje[5:]:
        out.append(Disparo("aniversario_dela", "aniversário do 1º commit da MAGI"))
    return out
