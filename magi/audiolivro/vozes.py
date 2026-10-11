"""Voz por trecho e elenco de personagens (tarefa A1.2; D1/D5; spec §3, requirements A4).

Sempre Kokoro, sempre na voz/idioma dela. Narração, título e pensamento sem falante na voz dela;
cada personagem com uma voz Kokoro do grupo gênero × idade, ≠ voz dela, a mesma no livro todo
(``Elenco`` persistido em ``elenco_dir/<livro_id>.json``, escrita atômica); grupo esgotado →
mistura nova ``a:0.6,b:0.4`` de duas vozes do grupo. Fala sem falante → voz padrão do gênero
(``f[0]``/``m[0]``); sem gênero → ``voz_dela:0.6,f[0]:0.4``. Velocidade e pausa pela emoção.
Grupos padrão em ``vozes.toml`` (sobrepostos por ``[audiolivro.vozes.<idioma>]``).
"""

from __future__ import annotations

import json
import logging
import os
import tomllib
import unicodedata
from collections.abc import Iterable
from dataclasses import replace
from functools import cache
from pathlib import Path

from magi.audiolivro.config import ConfigAudiolivro
from magi.audiolivro.contratos import Emocao, Genero, Idade, OpcoesVoz, Tipo, Trecho

log = logging.getLogger(__name__)

VOZES_PATH = Path(__file__).parent / "vozes.toml"
#: Velocidade final limitada a esta faixa (spec §3).
VELOCIDADE_MIN, VELOCIDADE_MAX = 0.7, 1.3
#: Trechos seguidos com as mesmas opções são juntados até este tamanho.
JUNTAR_ATE = 400
#: Emoção → (fator de velocidade, pausa em ms depois do trecho); spec §3.
EMOCAO: dict[Emocao, tuple[float, int]] = {
    Emocao.TENSA: (1.08, 150),
    Emocao.RAIVA: (1.08, 150),
    Emocao.GRITO: (1.08, 150),
    Emocao.MEDO: (1.04, 250),
    Emocao.TRISTE: (0.92, 450),
    Emocao.SUSSURRO: (0.92, 450),
    Emocao.CARINHO: (0.92, 450),
}
FATOR_TITULO, PAUSA_TITULO = 0.95, 700
FATOR_PENSAMENTO = 0.95
PAUSA_TROCA_VOZ = 250
#: Pesos das misturas novas quando o grupo esgota (o primeiro par é o da spec).
PESOS_MISTURA = ((0.6, 0.4), (0.7, 0.3), (0.8, 0.2))


@cache
def _padrao() -> dict[str, dict[str, tuple[str, ...]]]:
    with VOZES_PATH.open("rb") as f:
        raw = tomllib.load(f)
    return {
        idioma.lower(): {k: tuple(v) for k, v in g.items() if isinstance(v, list)}
        for idioma, g in raw.items()
        if isinstance(g, dict)
    }


def grupos(idioma: str, cfg: ConfigAudiolivro) -> dict[str, tuple[str, ...]]:
    """Grupos de voz do idioma dela: ``vozes.toml`` + sobreposição do config (chave a chave)."""
    idioma = idioma.lower()
    padrao = _padrao()
    base = padrao.get(idioma) or padrao["en-gb" if idioma.startswith("en") else "pt-br"]
    return {**base, **cfg.vozes.get(idioma, {})}


def normalizar(nome: str) -> str:
    """Nome do personagem sem acento, sem caixa e com espaços simples."""
    sem = unicodedata.normalize("NFKD", nome)
    sem = "".join(c for c in sem if not unicodedata.combining(c))
    return " ".join(sem.lower().split())


def _pesos(voz: str) -> dict[str, float]:
    """``"a:0.6,b:0.4"`` → ``{a: 0.6, b: 0.4}`` (normalizado; voz simples = peso 1)."""
    out: dict[str, float] = {}
    for parte in voz.split(","):
        nome, _, peso = parte.partition(":")
        out[nome.strip()] = out.get(nome.strip(), 0.0) + float(peso or 1)
    total = sum(out.values()) or 1.0
    return {k: v / total for k, v in out.items()}


def misturar(a: str, b: str, pa: float = 0.6, pb: float = 0.4) -> str:
    """Mistura Kokoro ``pa·a + pb·b`` (achata misturas; formato ``nome:peso,...``)."""
    mix: dict[str, float] = {}
    for voz, p in ((a, pa), (b, pb)):
        for nome, w in _pesos(voz).items():
            mix[nome] = mix.get(nome, 0.0) + p * w
    itens = sorted(mix.items(), key=lambda kv: -kv[1])
    if len(itens) == 1:
        return itens[0][0]
    return ",".join(f"{n}:{round(w, 2):g}" for n, w in itens)


class Elenco:
    """Personagem (nome normalizado) → voz Kokoro, por livro; gravação atômica."""

    def __init__(
        self,
        livro_id: str,
        voz_dela: str,
        idioma: str,
        cfg: ConfigAudiolivro,
        caminho: Path | None = None,
    ) -> None:
        self.livro_id = livro_id
        self.voz_dela = voz_dela
        self.idioma = idioma.lower()
        self.cfg = cfg
        self.caminho = caminho or cfg.elenco_dir / f"{livro_id}.json"
        self.grupos = grupos(self.idioma, cfg)
        self.vozes: dict[str, str] = self._abrir()

    def _abrir(self) -> dict[str, str]:
        try:
            dados = json.loads(self.caminho.read_text(encoding="utf-8"))
            vozes = dados.get("vozes", {})
            return {str(k): str(v) for k, v in vozes.items() if isinstance(v, str) and v}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, AttributeError) as e:
            log.warning("audiolivro: elenco %s ilegível (%s); começa vazio", self.caminho, e)
            return {}

    def _gravar(self) -> None:
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.caminho.with_suffix(".json.tmp")
        dados = {"livro": self.livro_id, "idioma": self.idioma, "vozes": self.vozes}
        tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.caminho)

    def _grupo(self, genero: Genero | None, idade: Idade | None) -> tuple[str, ...]:
        g = self.grupos
        faixa = {"crianca": "jovem", "jovem": "jovem", "idoso": "idoso"}.get(idade or "")
        chaves: list[str] = []
        if faixa:
            if genero:
                chaves.append(f"{faixa}_{genero}")
            chaves.append(faixa)
        chaves += [genero] if genero else ["f", "m"]
        for k in chaves:
            if k in g and g[k]:
                if not genero and k in ("f", "m"):  # sem gênero: f e m intercalados
                    f, m = g.get("f", ()), g.get("m", ())
                    return (
                        tuple(v for par in zip(f, m, strict=False) for v in par) + f[len(m) :] + m[len(f) :]
                    )
                return g[k]
        return g.get("f", ()) or (self.voz_dela,)

    def padrao(self, genero: Genero | None, idade: Idade | None = None) -> str:
        """Voz da fala sem falante: a primeira do grupo da idade (criança/jovem/idoso) ou do
        gênero; sem gênero nem idade, a dela misturada com ``f[0]``. Não grava no elenco."""
        f = self.grupos.get("f") or (self.voz_dela,)
        if idade in ("crianca", "jovem", "idoso"):
            livres = [v for v in self._grupo(genero, idade) if v != self.voz_dela]
            if livres:
                return livres[0]
        if genero in ("f", "m"):
            return (self.grupos.get(genero) or f)[0]
        return misturar(self.voz_dela, f[0])

    def voz(self, falante: str | None, genero: Genero | None, idade: Idade | None) -> str:
        """Voz do personagem (nova → primeira livre do grupo; gravada)."""
        if not falante or not normalizar(falante):
            return self.padrao(genero, idade)
        nome = normalizar(falante)
        if nome in self.vozes:
            return self.vozes[nome]
        voz = self._livre(self._grupo(genero, idade))
        self.vozes[nome] = voz
        try:
            self._gravar()
        except OSError as e:
            log.warning("audiolivro: não gravou o elenco %s (%s)", self.caminho, e)
        return voz

    def _livre(self, grupo: tuple[str, ...]) -> str:
        usadas = set(self.vozes.values()) | {self.voz_dela}
        candidatas = [v for v in grupo if v != self.voz_dela]
        for v in candidatas:
            if v not in usadas:
                return v
        base = candidatas or [v for vs in self.grupos.values() for v in vs if v != self.voz_dela]
        for pa, pb in PESOS_MISTURA:
            for a in base:
                for b in base:
                    if a != b and (v := misturar(a, b, pa, pb)) not in usadas:
                        return v
        log.info("audiolivro: vozes do grupo esgotadas; repete %s", base[0] if base else "?")
        return base[0] if base else self.voz_dela


def _velocidade(v: float) -> float:
    return round(min(VELOCIDADE_MAX, max(VELOCIDADE_MIN, v)), 3)


def opcoes(trecho: Trecho, elenco: Elenco, velocidade: float) -> OpcoesVoz:
    """``OpcoesVoz`` Kokoro do trecho (``lang`` = idioma dela). ``pausa_ms`` = 0 nas emoções
    "demais"; a pausa de troca de voz entra na ``juntar``."""
    if trecho.tipo is Tipo.TITULO:
        fator, pausa, voz = FATOR_TITULO, PAUSA_TITULO, elenco.voz_dela
    else:
        fator, pausa = EMOCAO.get(trecho.emocao, (1.0, 0))
        if trecho.tipo is Tipo.FALA or trecho.falante:
            voz = elenco.voz(trecho.falante, trecho.genero, trecho.idade)
        else:
            voz = elenco.voz_dela
        if trecho.tipo is Tipo.PENSAMENTO:
            fator *= FATOR_PENSAMENTO
    return OpcoesVoz(voice=voz, speed=_velocidade(velocidade * fator), lang=elenco.idioma, pausa_ms=pausa)


def juntar(partes: Iterable[tuple[str, OpcoesVoz]]) -> list[tuple[str, OpcoesVoz]]:
    """Junta partes seguidas com opções iguais até ``JUNTAR_ATE`` caracteres; depois põe
    ``PAUSA_TROCA_VOZ`` nas partes sem pausa seguidas de outra voz."""
    out: list[tuple[str, OpcoesVoz]] = []
    for texto, op in partes:
        if not texto:
            continue
        if out and out[-1][1] == op and len(out[-1][0]) + 1 + len(texto) <= JUNTAR_ATE:
            out[-1] = (f"{out[-1][0]} {texto}", op)
        else:
            out.append((texto, op))
    for i in range(len(out) - 1):
        texto, op = out[i]
        if op.pausa_ms == 0 and op.voice != out[i + 1][1].voice:
            out[i] = (texto, replace(op, pausa_ms=PAUSA_TROCA_VOZ))
    return out


def partes(trechos: Iterable[Trecho], elenco: Elenco, velocidade: float) -> list[tuple[str, OpcoesVoz]]:
    """Trechos → partes prontas para o ``say_parts`` (A2.1): opções e junção."""
    return juntar((t.texto, opcoes(t, elenco, velocidade)) for t in trechos)
