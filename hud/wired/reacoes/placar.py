"""Placar "Condessa × Pedro" (acordo placar-e-jogo §3), só lazer. Dono: V1.4.

Módulo puro: o relógio (``agora``, epoch) vem sempre de quem chama e nada aqui grava em disco. Cada
ponto volta como a linha pronta para o ``reacoes.jsonl`` (``registro.linha_placar``); o total do dia
e da semana sai em ``exportar()`` para o ``Estado`` guardar (a ligação é da V1.7).

Números do ``[vida.placar]`` (``fecha_dia_h``, ``ativo_depois_h``, ``viradas_dia``, ``tetos``); teto
0 desliga a fonte. Trabalho (commit, faxina, Claude), voltas, cliques e "sem sentido" nunca contam:
fonte fora de ``tetos`` é recusada.
"""

from __future__ import annotations

import datetime as _dt
import time
from dataclasses import dataclass

from .registro import linha_placar
from .vida import VIDA_PADRAO, mesclar

# fonte -> lado (tabela do acordo §3)
FONTES: dict[str, str] = {
    "ele_partida_limpa": "ele",
    "ele_faixa_nota2": "ele",
    "ele_truque_ignorado": "ele",
    "ela_partida_episodio": "ela",
    "ela_pulo_nota2": "ela",
    "ela_truque_aplaudido": "ela",
    "ela_favorita_ado": "ela",
    "ela_ativo_madrugada": "ela",
}
NUNCA_CONTAM = frozenset({"commit", "faxina", "claude_fim", "claude_erro", "pedro_volta",
                          "clique_carinho", "sem_sentido"})
VIRADA = {"ela": "piscadinha", "ele": "soprando_franja"}  # passivas que já existem
NOME_FONTE = {
    "ele_partida_limpa": "partida limpa",
    "ele_faixa_nota2": "faixa até o fim",
    "ele_truque_ignorado": "resistiu ao truque",
    "ela_partida_episodio": "partida suada",
    "ela_pulo_nota2": "pulou a faixa",
    "ela_truque_aplaudido": "truque convenceu",
    "ela_favorita_ado": "Ado até o fim",
    "ela_ativo_madrugada": "acordado depois da 1h",
}
POS_BATALHA = {
    "ele_partida_limpa": "Partida limpa. Ponto seu. Não se acostume.",
    "ela_partida_episodio": "Suou nessa, hein? Ponto meu.",
}
MAX_LINHA = 70
DIAS_GUARDADOS = 14


@dataclass
class Ponto:
    lado: str
    fonte: str
    ref: str
    linha: dict  # para o reacoes.jsonl (causa placar:<fonte>, campo placar)
    virada: dict | None = None  # {"chave", "causa": "placar:virada", "lado", "ref"} ou None


def _vazio() -> dict:
    return {"ela": 0, "ele": 0, "fontes": {}, "viradas": 0, "lider": None}


class Placar:
    def __init__(self, vida: dict | None = None):
        cfg = mesclar(VIDA_PADRAO["placar"], (vida or {}).get("placar") or {})
        self.liga = bool(cfg.get("liga", True))
        self.fecha_dia_h = int(cfg["fecha_dia_h"])
        self.ativo_depois_h = int(cfg["ativo_depois_h"])
        self.viradas_dia = int(cfg["viradas_dia"])
        self.tetos: dict[str, int] = {k: int(v) for k, v in cfg["tetos"].items()}
        self.dias: dict[str, dict] = {}
        self.ultimos: list[dict] = []  # 3 últimos {lado, fonte, ref, t}

    # ---- dia e semana ----
    def dia(self, agora: float) -> str:
        """Dia do placar: fecha às ``fecha_dia_h`` (a madrugada conta no dia anterior)."""
        lt = time.localtime(agora)
        d = _dt.date(lt.tm_year, lt.tm_mon, lt.tm_mday)
        if lt.tm_hour < self.fecha_dia_h:
            d -= _dt.timedelta(days=1)
        return d.isoformat()

    def _total(self, dia: str) -> tuple[int, int]:
        r = self.dias.get(dia)
        return (r["ela"], r["ele"]) if r else (0, 0)

    def hoje(self, agora: float) -> tuple[int, int]:
        """(Condessa, Pedro) do dia."""
        return self._total(self.dia(agora))

    def semana(self, agora: float) -> tuple[int, int]:
        """(Condessa, Pedro) da semana ISO (segunda a domingo) do dia do placar."""
        d = _dt.date.fromisoformat(self.dia(agora))
        ini = d - _dt.timedelta(days=d.weekday())
        ela = ele = 0
        for i in range(7):
            a, b = self._total((ini + _dt.timedelta(days=i)).isoformat())
            ela, ele = ela + a, ele + b
        return ela, ele

    # ---- pontos ----
    def pontuar(self, fonte: str, ref: str, agora: float) -> Ponto | None:
        """Conta um ponto se a fonte vale e o teto do dia deixa; ``ref`` (id da linha de origem) é
        obrigatório. Devolve o ponto com a linha do registro e, se o líder trocou (≤ ``viradas_dia``),
        a virada."""
        if not ref:
            raise ValueError("ponto do placar sem ref")
        if not self.liga or fonte in NUNCA_CONTAM or fonte not in FONTES:
            return None
        dia = self.dia(agora)
        r = self.dias.setdefault(dia, _vazio())
        if r["fontes"].get(fonte, 0) >= self.tetos.get(fonte, 0):
            return None
        lado = FONTES[fonte]
        r["fontes"][fonte] = r["fontes"].get(fonte, 0) + 1
        r[lado] += 1
        self.ultimos = ([{"lado": lado, "fonte": fonte, "ref": ref, "t": agora}] + self.ultimos)[:3]
        self._podar(dia)
        p = Ponto(lado, fonte, ref, linha_placar(lado, fonte, ref, agora))
        lider = "ela" if r["ela"] > r["ele"] else "ele" if r["ele"] > r["ela"] else None
        if lider is not None:
            if r["lider"] is not None and lider != r["lider"] and r["viradas"] < self.viradas_dia:
                r["viradas"] += 1
                p.virada = {"chave": VIRADA[lider], "causa": "placar:virada", "lado": lider,
                            "ref": ref}
            r["lider"] = lider
        return p

    def ativo(self, agora: float, ref: str) -> Ponto | None:
        """Pedro ativo depois de ``ativo_depois_h`` (até o dia fechar): ponto dela, teto 1."""
        h = time.localtime(agora).tm_hour
        if not (self.ativo_depois_h <= h < self.fecha_dia_h):
            return None
        return self.pontuar("ela_ativo_madrugada", ref, agora)

    def _podar(self, dia: str) -> None:
        for d in sorted(self.dias)[:-DIAS_GUARDADOS]:
            if d != dia:
                del self.dias[d]

    # ---- texto ----
    def resumo(self, agora: float) -> dict:
        """Para o hover: ``Condessa X × Y Pedro · semana X × Y`` + os 3 últimos com a fonte."""
        ela, ele = self.hoje(agora)
        sa, se = self.semana(agora)
        return {
            "texto": f"Condessa {ela} × {ele} Pedro · semana {sa} × {se}",
            "ultimos": [f"{'Condessa' if u['lado'] == 'ela' else 'Pedro'} +1 · "
                        f"{NOME_FONTE[u['fonte']]}" for u in self.ultimos],
        }

    @staticmethod
    def linha_pos_batalha(ponto: Ponto | None) -> str | None:
        """1 linha ≤ 70 só se a partida mexeu no placar (na expressão que já sai)."""
        if ponto is None:
            return None
        return POS_BATALHA.get(ponto.fonte)

    def bom_dia(self, agora: float) -> str | None:
        """O resultado de ontem (dia do placar anterior) em 1 linha ≤ 70; nada se não houve ponto."""
        ontem = (_dt.date.fromisoformat(self.dia(agora)) - _dt.timedelta(days=1)).isoformat()
        ela, ele = self._total(ontem)
        if ela == ele == 0:
            return None
        if ela > ele:
            return f"Ontem: {ela} × {ele} pra mim. Revanche?"
        if ele > ela:
            return f"Ontem: {ele} × {ela} pra você. Não se acostume."
        return f"Ontem: {ela} × {ele}. Empate é empate."

    # ---- estado ----
    def exportar(self) -> dict:
        return {"dias": {d: {**r, "fontes": dict(r["fontes"])} for d, r in self.dias.items()},
                "ultimos": [dict(u) for u in self.ultimos]}

    def importar(self, dados: dict | None) -> None:
        dados = dados or {}
        self.dias = {}
        for d, r in (dados.get("dias") or {}).items():
            try:
                _dt.date.fromisoformat(d)
                self.dias[d] = {"ela": int(r.get("ela", 0)), "ele": int(r.get("ele", 0)),
                                "fontes": {k: int(v) for k, v in (r.get("fontes") or {}).items()},
                                "viradas": int(r.get("viradas", 0)), "lider": r.get("lider")}
            except (TypeError, ValueError, AttributeError):
                continue
        self.ultimos = [dict(u) for u in (dados.get("ultimos") or [])
                        if isinstance(u, dict) and u.get("fonte") in FONTES][:3]
