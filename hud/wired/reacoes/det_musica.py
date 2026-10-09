"""Detector `det_musica` (spec §5): 24–30, 32, 33, 78, 81, 83, 85, 89, I3, I7–I15. Dono: R1.2.

As 19 reações antigas de música (`music_love`, `music_new`, `skips`… pela nota da faixa) seguem em
``Reactor._music``/``_decide``; aqui só entram as reações novas e as variantes 33, I3, I12, I13.

Tudo sai do ``Snapshot`` (``snap.track``: ``title``, ``artist``, ``position``, ``length``,
``playing``) e do ``ctx`` (``veredito``, ``musica_nota``, ``ado``, ``jogo``, ``fps_estavel``,
``favorita_dia``, ``hora``, ``agora``, ``relogio``, ``taste``). O estado entre ticks fica nas chaves
``_musica_*`` do próprio ``ctx``:

* ``_musica_faixa``/``_musica_desde``/``_musica_nota``: faixa atual, desde quando e nota.
* ``_musica_nota_ant``: nota da faixa anterior (81).
* ``_musica_plays``: ``(dia, {faixa: plays})`` (28) · ``_musica_artistas``: artistas já ouvidos (33).
* ``_musica_pulos``: instantes dos pulos (I3) · ``_musica_seq``: pulos seguidos antes da atual (83).
* ``_musica_dirs``: ``(instante, "next"/"prev")`` das trocas (89)
* ``_musica_hist``/``_musica_i``: fila vista e cursor (89).
* ``_musica_toggles``: instantes de play/pause (85) · ``_musica_parou``: ``(instante, fim_da_fila)``.
* ``_musica_feitas``: reações já tocadas nesta faixa (1×/faixa) · ``_musica_fps``: FPS estável desde.

Pulo = troca de faixa antes do fim (posição < duração − 3 s; sem posição, < 30 s de faixa). Os
cliques do HUD não chegam ao ``ctx``: "botão" (85, 89) é inferido do player.
"""

from __future__ import annotations

import time
import unicodedata
from typing import Any

from .contratos import EFEITO, Disparo

FIM_FILA_S = 3.0  # 32: parou a menos disso do fim
FILA_ESPERA_S = 10.0  # 32: nada começou nesse tempo
PULO_SEM_POSICAO_S = 30.0
REFRAO_S = 60.0  # 26 (nunca antes disso)
CANTAR_S = 40.0  # 27
CONTA_S = 40.0  # I9
ELEVADOR_S = 60.0  # I14
CHEFE_S = 120.0  # I13
PIOU_ESSA_S = 20.0  # I15
AGORA_SIM_S = 15.0  # 83: parou de pular nessa faixa há isso
TONTURA = (5, 60.0)  # I3: pulos em s
MESMO_BOTAO = (3, 10.0)  # 85
INDECISA = (2, 15.0)  # 89: alternâncias em s
REPETIDA = 3  # 28: 3ª reprodução no dia
CANTAR_PLAYS = 5  # 27

TITULO_DESCONFIADA = ("slowed", "sped up", "nightcore")  # 78
CONTA_ANONIMA = ("kenshi yonezu", "hachi", "米津玄師")  # I9 (+ gênero vocaloid)
CHOPIN = ("frederic chopin", "chopin", "marika takeuchi")  # I12
DIVA = "lady gaga"  # I10
_LISTAS = {  # recaída sem o gosto
    "melancolica": ["frederic chopin", "chopin", "arvo part", "marika takeuchi", "laufey",
                    "sergei rachmaninoff", "rachmaninoff"],
    "melancolica_titulo": ["nocturne", "noturno", "requiem", "sad", "triste", "lagrima"],
    "danca": ["dance", "disco", "house", "eurobeat", "phonk", "j-rock", "rock", "metal", "pop", "kpop"],
}
_AGUA = ["agua", "water", "rain", "chuva", "mar", "sea", "ocean", "oceano", "lake", "lago", "river",
         "rio", "wave", "onda", "reflets dans l'eau", "la mer"]
_PROIBIDO_ADO = (EFEITO["D1"], "D1")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c)).strip()


def _compacto(s: str) -> str:
    return _norm(s).replace("-", "").replace(" ", "")


def _palavras(texto: str, lista) -> bool:
    """Alguma expressão da lista aparece como palavra(s) inteira(s) em ``texto``."""
    t = f" {''.join(c if c.isalnum() or c == chr(39) else ' ' for c in _norm(texto))} "
    t = " ".join(t.split())
    return any(f" {_norm(w)} " in f" {t} " for w in lista if w)


def _secao(ctx: dict, nome: str) -> dict:
    taste = ctx.get("taste")
    try:
        return dict(taste.section(nome)) if taste is not None else {}
    except Exception:  # noqa: BLE001 — gosto quebrado não derruba o detector
        return {}


def _lista(ctx: dict, nome: str) -> list[str]:
    return list(_secao(ctx, "listas").get(nome) or _LISTAS[nome])


def _dia(ctx: dict) -> str:
    return time.strftime("%Y%m%d", time.localtime(float(ctx.get("relogio") or time.time())))


def _faixa(snap: Any) -> tuple[tuple[str, str] | None, Any]:
    tr = getattr(snap, "track", None) if snap is not None else None
    if tr is None or not getattr(tr, "title", None):
        return None, tr
    return (tr.title or "", tr.artist or ""), tr


def _janela(ctx: dict, chave: str, agora: float, janela: float) -> list:
    lst = [x for x in ctx.get(chave, []) if agora - (x[0] if isinstance(x, tuple) else x) <= janela]
    ctx[chave] = lst
    return lst


def _artista(ctx: dict, artist: str) -> str:
    v = ctx.get("veredito")
    return getattr(v, "artist", "") or _norm(artist)


def _artistas(artist: str) -> list[str]:
    """Nomes do campo artista ("A, B feat. C"), normalizados."""
    out = _norm(artist)
    for sep in (" feat. ", " feat ", " ft. ", " & ", " x ", ";", "/"):
        out = out.replace(sep, ",")
    return [a.strip() for a in [_norm(artist), *out.split(",")] if a.strip()]


def detectar(anterior: Any, snap: Any, ctx: dict) -> list[Disparo]:
    """Compara o Snapshot ``anterior`` com ``snap`` e devolve os disparos deste tick."""
    agora = float(ctx.get("agora", 0.0))
    chave, tr = _faixa(snap)
    tocando = bool(chave and getattr(tr, "playing", False))
    if "_musica_faixa" not in ctx:  # primeiro tick: só aprende o estado
        ctx.update(_musica_faixa=chave, _musica_desde=agora, _musica_tocando=tocando,
                   _musica_nota=int(ctx.get("musica_nota", 0)), _musica_pos=None,
                   _musica_hist=[chave] if chave else [])
        return []
    out: list[Disparo] = []
    out += _tocar_parar(ctx, chave, tocando, agora)
    if chave != ctx["_musica_faixa"]:
        out += _troca(ctx, chave, agora)
    if chave is not None:
        out += _durante(ctx, chave, tr, tocando, agora)
        ctx["_musica_pos"] = (getattr(tr, "position", None), getattr(tr, "length", None))
    ctx["_musica_tocando"] = tocando
    if ctx.get("ado"):
        out = [d for d in out if not _proibido_ado(ctx, d)]
    return out


def _proibido_ado(ctx: dict, d: Disparo) -> bool:
    """Ado nunca recebe blush (D1) nem fundo ``love``."""
    if d.chave in ("music_love", "surpresa_boa", "corando"):
        return True
    df = (ctx.get("defs") or {}).get((d.chave, d.variante) if d.variante else d.chave)
    if df is None:
        return False
    return df.mood == "love" or any(e in _PROIBIDO_ADO for p in df.passos for e in p.efeitos)


# ------------------------------------------------------------ play/pause e fim da fila

def _tocar_parar(ctx: dict, chave, tocando: bool, agora: float) -> list[Disparo]:
    out: list[Disparo] = []
    antes = bool(ctx.get("_musica_tocando"))
    if tocando != antes:
        if chave is not None and chave == ctx.get("_musica_faixa"):
            toggles = _janela(ctx, "_musica_toggles", agora, MESMO_BOTAO[1])
            toggles.append(agora)
            if len(toggles) >= MESMO_BOTAO[0]:
                ctx["_musica_toggles"] = []
                out.append(Disparo("indiferente", "mesmo_botao"))
        if tocando and not ctx.get("_musica_parou"):
            out.append(Disparo("colocando_fone", "musica_comecou"))
        elif not tocando:
            pos, dur = ctx.get("_musica_pos") or (None, None)
            fim = pos is not None and bool(dur) and pos >= dur - FIM_FILA_S
            ctx["_musica_parou"] = (agora, fim)
        if tocando:
            ctx["_musica_parou"] = None
    parou = ctx.get("_musica_parou")
    if parou and not tocando and agora - parou[0] >= FILA_ESPERA_S:
        ctx["_musica_parou"] = None
        out.append(Disparo("acabou_fila", "fim_da_fila") if parou[1]
                   else Disparo("tirando_fone", "musica_parou"))
    return out


# ------------------------------------------------------------ troca de faixa

def _troca(ctx: dict, chave, agora: float) -> list[Disparo]:
    out: list[Disparo] = []
    velha, desde = ctx.get("_musica_faixa"), float(ctx.get("_musica_desde", agora))
    nota_velha = int(ctx.get("_musica_nota", 0))
    pulo = False
    if velha is not None and chave is not None:
        pos, dur = ctx.get("_musica_pos") or (None, None)
        pulo = pos < dur - FIM_FILA_S if pos is not None and dur else agora - desde < PULO_SEM_POSICAO_S
    if pulo:
        pulos = _janela(ctx, "_musica_pulos", agora, TONTURA[1])
        pulos.append(agora)
        if len(pulos) >= TONTURA[0]:
            ctx["_musica_pulos"] = []
            out.append(Disparo("skips", "tontura", "tontura"))
        if nota_velha == 2 and agora - desde < PIOU_ESSA_S:
            out.append(Disparo("pulou_essa", "pulou_nota_2"))
        ctx["_musica_seq"] = int(ctx.get("_musica_seq", 0)) + 1
    else:
        ctx["_musica_seq"] = 0
    hist = ctx.setdefault("_musica_hist", [])  # fila vista, com o cursor na faixa atual
    i = int(ctx.get("_musica_i", len(hist) - 1))
    direcao = "next"
    if i >= 1 and hist[i - 1] == chave:
        direcao, i = "prev", i - 1
    elif chave is not None and i + 1 < len(hist) and hist[i + 1] == chave:
        i += 1
    elif chave is not None:
        del hist[i + 1:]
        hist.append(chave)
        del hist[:-6]
        i = len(hist) - 1
    ctx["_musica_i"] = i
    if velha is not None and chave is not None:  # 89: direção da troca
        dirs = _janela(ctx, "_musica_dirs", agora, INDECISA[1])
        dirs.append((agora, direcao))
        trocas = sum(1 for a, b in zip(dirs, dirs[1:], strict=False) if a[1] != b[1])
        if trocas >= INDECISA[0]:
            ctx["_musica_dirs"] = []
            out.append(Disparo("indecisa", "anterior_proxima"))
    ctx["_musica_nota_ant"] = nota_velha if velha is not None else None
    ctx.update(_musica_faixa=chave, _musica_desde=agora, _musica_feitas=set(), _musica_fps=None,
               _musica_pos=None, _musica_nota=int(ctx.get("musica_nota", 0)))
    if chave is not None:
        out += _comecou(ctx, chave)
    return out


def _comecou(ctx: dict, chave: tuple[str, str]) -> list[Disparo]:
    """Gatilhos de faixa nova (a nota já é a do veredito desta faixa)."""
    title, artist = chave
    nota = int(ctx.get("musica_nota", 0))
    art = _artista(ctx, artist)
    nomes = {art, *_artistas(artist)}
    v = ctx.get("veredito")
    generos = {_compacto(g) for g in getattr(v, "genres", ()) or ()}
    hora = int(ctx.get("hora", 12))
    fmt = {"artist": artist}
    out: list[Disparo] = []

    dia, plays = ctx.get("_musica_plays") or ("", {})
    if dia != _dia(ctx):
        dia, plays = _dia(ctx), {}
    plays[chave] = n = plays.get(chave, 0) + 1
    ctx["_musica_plays"] = (dia, plays)
    ctx["_musica_n"] = n
    vistos = ctx.setdefault("_musica_artistas", set())
    novo = bool(art) and art not in vistos
    vistos.add(art)

    if n == REPETIDA and not ctx.get("ado"):  # Ado: variante `happy` sem Def (Sobras)
        out.append(Disparo("musica_repetida", "terceira_vez", fmt=fmt))
    if novo and nota >= 1:
        out.append(Disparo("music_new", "artista_novo_amou", "amou", fmt))
    triste = nomes & {_norm(a) for a in _lista(ctx, "melancolica")} or _palavras(
        title, _lista(ctx, "melancolica_titulo"))
    if nomes & set(CHOPIN) and hora < 4:
        out.append(Disparo("musica_triste", "chopin_madrugada", "chopin", fmt))
    elif triste:
        out.append(Disparo("musica_triste", "melancolica", fmt=fmt))
    if nota >= 1 and generos & {_compacto(g) for g in _lista(ctx, "danca")}:
        out.append(Disparo("musica_dancante", "danca", fmt=fmt))
    if _palavras(title, TITULO_DESCONFIADA):
        out.append(Disparo("desconfiada", "titulo_alterado", fmt=fmt))
    if nota == 2 and ctx.get("_musica_nota_ant") == -1:
        out.append(Disparo("surpresa_boa", "virada", fmt=fmt))
    fav = ctx.get("favorita_dia") or ""
    if fav and fav in nomes and ctx.get("_musica_fav_dia") != dia:
        ctx["_musica_fav_dia"] = dia
        out.append(Disparo("favorita_dia", "favorita_do_dia", fmt=fmt))
    if ctx.get("ado") or "ado" in nomes:
        out.append(Disparo("duelo_ado", "ado", fmt=fmt))
    if DIVA in nomes:
        out.append(Disparo("diva_diva", "lady_gaga", fmt=fmt))
    if _palavras(title, _secao(ctx, "titulo").get("agua") or _AGUA):
        out.append(Disparo("tema_agua", "titulo_agua", fmt=fmt))
    return out


# ------------------------------------------------------------ enquanto toca

def _durante(ctx: dict, chave, tr, tocando: bool, agora: float) -> list[Disparo]:
    out: list[Disparo] = []
    feitas: set = ctx.setdefault("_musica_feitas", set())
    tempo = agora - float(ctx.get("_musica_desde", agora))
    nota = int(ctx.get("musica_nota", 0))
    title, artist = chave
    fmt = {"artist": artist}

    def uma(d: Disparo, cond: bool) -> None:
        k = (d.chave, d.variante)
        if cond and tocando and k not in feitas:
            feitas.add(k)
            out.append(d)

    if ctx.get("jogo") and ctx.get("fps_estavel", True):
        ctx["_musica_fps"] = ctx.get("_musica_fps") or agora
    else:
        ctx["_musica_fps"] = None
    v = ctx.get("veredito")
    generos = {_compacto(g) for g in getattr(v, "genres", ()) or ()}
    nomes = {_artista(ctx, artist), *_artistas(artist)}
    n = int(ctx.get("_musica_n", 1))
    cantar = tempo >= CANTAR_S and (nota == 2 or n >= CANTAR_PLAYS)
    uma(Disparo("cantando_junto", "cantando", fmt=fmt), cantar)
    uma(Disparo("refrao", "sem_pulo_60s", fmt=fmt), tempo >= REFRAO_S and nota == 2)
    uma(Disparo("elevador", "nota_ruim_60s", fmt=fmt), tempo >= ELEVADOR_S and nota == -1)
    uma(Disparo("conta_anonima", "vocaloid", fmt=fmt),
        tempo >= CONTA_S and ("vocaloid" in generos or bool(nomes & set(CONTA_ANONIMA))))
    uma(Disparo("piscadinha", "agora_sim", fmt=fmt),
        tempo >= AGORA_SIM_S and nota == 2 and int(ctx.get("_musica_seq", 0)) >= 2)
    fps = ctx.get("_musica_fps")
    uma(Disparo("music_love", "modo_chefe", "chefe", fmt),
        nota == 2 and "trilha" in generos and fps is not None and agora - fps >= CHEFE_S)
    return out
