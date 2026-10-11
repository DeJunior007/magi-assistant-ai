"""“Isso foi sem sentido” (acordo-pj §4). Dono: V1.5.

O Pedro marca uma expressão (✗ no hover, atalho, voz). ``marcar`` grava em
``~/.local/state/magi/sem-sentido.jsonl`` a linha de origem inteira (a do ``reacoes.jsonl``) + hora +
gesto; sem expressão alvo grava ``alvo: "nenhum"`` (também é dado). Marcar de novo o mesmo alvo em
≤ ``desfazer_s`` desfaz (linha ``desfeito``). A reação (``REACAO``: ``B7 C12 ?`` 700 ms) não mexe no
ânimo, não conta no placar e fica fora do ritmo e das metas: quem toca é o diretor (V1.8).

Ajuste: cada marca ativa nos últimos ``janela_dias`` multiplica por ``fator`` o peso **daquela
variante no grupo daquele momento**, com ``piso`` (nunca some); ``passivas.sortear`` aceita o
dicionário de ``fatores``. Cenas e negativas não mudam de peso (são por regra): vão direto para a
``pauta``. A pauta lista o que tem ≥ ``pauta_marcas`` marcas ou ≥ ``pauta_fracao`` das ocorrências.
**Nunca escreve no gosto** (``condessa-gosto.toml``): os números vêm do ``[vida.sem_sentido]``.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from .vida import VIDA_PADRAO

SEM_SENTIDO_FILE = Path.home() / ".local/state/magi/sem-sentido.jsonl"
DIA_S = 86400.0
NENHUM = "nenhum"
GESTOS = ("hover", "atalho", "voz")
AJUSTAVEIS = frozenset({"gesto", "passiva"})  # tipos do reacoes.jsonl que mudam de peso
POR_REGRA = frozenset({"cena"})  # cenas (e negativas) vão direto para a pauta


@dataclass(frozen=True)
class Reacao:
    """O “hm… anotado”: sem ânimo, sem placar, fora do ritmo e das metas."""
    rosto: str = "B7 C12 ?"
    ms: int = 700
    animo: float = 0.0
    placar: bool = False
    ritmo: bool = False


REACAO = Reacao()


def _cfg(vida: dict | None) -> dict:
    base = VIDA_PADRAO["sem_sentido"]
    return {**base, **((vida or {}).get("sem_sentido") or {})}


def _ident(alvo: dict | str) -> tuple:
    if not isinstance(alvo, dict):
        return (NENHUM,)
    return (alvo.get("t"), alvo.get("chave"), alvo.get("variante"))


class SemSentido:
    """Marcas do Pedro. ``negativas`` = chaves de passiva negativa (``passivas.NEGATIVAS``)."""

    def __init__(self, vida: dict | None = None, caminho: Path | None = None,
                 negativas: frozenset[str] | set[str] = frozenset()):
        self.cfg = _cfg(vida)
        self.caminho = caminho
        self.negativas = frozenset(negativas)
        self.marcas: list[dict] = []  # linhas de marca (com ``desfeito`` quando desfeitas)
        self._carregar()

    # ------------------------------------------------------------ arquivo
    def _arquivo(self) -> Path:
        return self.caminho or SEM_SENTIDO_FILE

    def _carregar(self) -> None:
        try:
            linhas = self._arquivo().read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        for txt in linhas:
            try:
                linha = json.loads(txt)
            except ValueError:
                continue
            if "desfeito" in linha:
                for m in self.marcas:
                    if m["t"] == linha["desfeito"]:
                        m["desfeito"] = linha["t"]
            elif "alvo" in linha:
                self.marcas.append(linha)

    def _gravar(self, linha: dict) -> None:
        caminho = self._arquivo()
        try:
            caminho.parent.mkdir(parents=True, exist_ok=True)
            with caminho.open("a", encoding="utf-8") as f:
                f.write(json.dumps(linha, ensure_ascii=False) + "\n")
        except OSError:
            pass  # o registro nunca derruba o HUD

    # ------------------------------------------------------------ gestos
    def marcar(self, alvo: dict | None, gesto: str, agora: float) -> dict:
        """Marca ``alvo`` (linha de origem do ``reacoes.jsonl``; None = ``nenhum``). O mesmo alvo de
        novo em ≤ ``desfazer_s`` desfaz a marca anterior. Devolve a linha gravada."""
        alvo_ = dict(alvo) if alvo else NENHUM
        ult = self.marcas[-1] if self.marcas else None
        if (ult is not None and "desfeito" not in ult and agora - ult["t"] <= self.cfg["desfazer_s"]
                and _ident(ult["alvo"]) == _ident(alvo_)):
            return self.desfazer(agora, gesto)
        linha = {"t": agora, "hora": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(agora)),
                 "gesto": gesto, "alvo": alvo_}
        self.marcas.append(linha)
        self._gravar(linha)
        return linha

    def desfazer(self, agora: float, gesto: str = "") -> dict | None:
        """Desfaz a última marca se ela tem ≤ ``desfazer_s``; grava a linha ``desfeito``."""
        ult = self.marcas[-1] if self.marcas else None
        if ult is None or "desfeito" in ult or agora - ult["t"] > self.cfg["desfazer_s"]:
            return None
        ult["desfeito"] = agora
        linha = {"t": agora, "hora": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(agora)),
                 "gesto": gesto, "desfeito": ult["t"]}
        self._gravar(linha)
        return linha

    # ------------------------------------------------------------ leitura
    def ativas(self, agora: float) -> list[dict]:
        """Marcas não desfeitas dentro da janela de ``janela_dias``."""
        janela = self.cfg["janela_dias"] * DIA_S
        return [m for m in self.marcas if "desfeito" not in m and 0 <= agora - m["t"] < janela]

    def _ajustavel(self, alvo) -> bool:
        return (isinstance(alvo, dict) and alvo.get("tipo") in AJUSTAVEIS
                and alvo.get("chave") not in self.negativas)

    def _contagem(self, agora: float) -> dict[tuple[str, str], list[dict]]:
        """(momento, variante) → marcas ativas ajustáveis."""
        out: dict[tuple[str, str], list[dict]] = {}
        for m in self.ativas(agora):
            a = m["alvo"]
            if self._ajustavel(a):
                out.setdefault((str(a.get("momento") or ""), str(a["chave"])), []).append(m)
        return out

    def fatores(self, momento, agora: float) -> dict[str, float]:
        """Variante → multiplicador do peso no grupo de ``momento`` (×``fator`` por marca, ≥ ``piso``)."""
        f, piso = self.cfg["fator"], self.cfg["piso"]
        mom = str(momento)
        return {var: max(piso, f ** len(ms))
                for (m, var), ms in self._contagem(agora).items() if m == mom}

    def ajustes(self, agora: float) -> int:
        """Quantos pares (momento, variante) estão com o peso ajustado agora (“ajustes: N”)."""
        return len(self._contagem(agora))

    def pauta(self, agora: float, ocorrencias: dict[str, int] | None = None) -> list[dict]:
        """Itens para a próxima pauta do Conselho, com as linhas do log. Cenas e negativas entram
        com 1 marca; o resto com ≥ ``pauta_marcas`` marcas ou ≥ ``pauta_fracao`` das
        ``ocorrencias`` (variante → vezes que saiu na janela). ``alvo: nenhum`` não entra."""
        grupos: dict[tuple[str, str], list[dict]] = {}
        for m in self.ativas(agora):
            a = m["alvo"]
            if not isinstance(a, dict) or not a.get("chave"):
                continue
            grupos.setdefault((str(a.get("momento") or ""), str(a["chave"])), []).append(m)
        ocorrencias = ocorrencias or {}
        out = []
        for (mom, chave), ms in grupos.items():
            a = ms[-1]["alvo"]
            regra = a.get("tipo") in POR_REGRA or chave in self.negativas
            occ = ocorrencias.get(chave, 0)
            if (regra or len(ms) >= self.cfg["pauta_marcas"]
                    or (occ > 0 and len(ms) / occ >= self.cfg["pauta_fracao"])):
                out.append({"chave": chave, "momento": mom, "tipo": a.get("tipo"), "marcas": len(ms),
                            "por_regra": regra, "linhas": ms})
        return out

    def exportar(self, agora: float) -> dict:
        """Para o ``condessa-estado.json``: ajustes vigentes e a pauta (a ligação é da V1.7/V1.8)."""
        ajustes = {f"{m}:{v}": max(self.cfg["piso"], self.cfg["fator"] ** len(ms))
                   for (m, v), ms in self._contagem(agora).items()}
        return {"ajustes": ajustes, "pauta": [{k: i[k] for k in ("chave", "momento", "marcas")}
                                              for i in self.pauta(agora)]}
