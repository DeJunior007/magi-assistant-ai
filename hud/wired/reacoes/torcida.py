"""Piso da ``torcida`` (acordo placar-e-jogo §1). Puro, relógio injetado (``agora`` em segundos).

Relógio "desde a última positiva": só anda com jogo aberto e o Pedro presente (pausa fora disso);
qualquer positiva (a lista do teste da meta 6, inclusive a própria ``torcida``) zera.

- ≥ ``forca_slot_min``: o próximo slot de passiva em Jogando é ``torcida`` (não sorteia);
- ≥ ``fura_slot_min``: sai fora de slot (o ``Governador`` ainda cobra os 25 s entre expressões, os
  60 s pós-cena e o teto de passivas: ocupa a vaga, não soma);
- máx. 1 a cada ``intervalo_min``; causa ``jogando_sem_positiva:<min>``; as 2 variantes alternam.

Números do ``[vida.torcida]``. Quem chama (Reactor, V1.7) faz ``atualizar`` a cada tick, ``positiva``
quando sai uma positiva, ``no_slot`` no slot de passiva em Jogando e ``fora_do_slot`` entre slots.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .catalogo import TORCIDA
from .governador import Governador, Pedido, Tipo
from .vida import VIDA_PADRAO, Momento, mesclar

CHAVE = "torcida"
CAUSA = "jogando_sem_positiva"
VARIANTES: tuple[str | None, ...] = tuple(None if isinstance(v, str) else v[1] for v in TORCIDA)


@dataclass(frozen=True)
class Escolha:
    chave: str
    var: str | None
    causa: str  # ``jogando_sem_positiva:<min>``
    delta_animo: float
    fora_de_slot: bool


class Torcida:
    def __init__(self, vida: dict | None = None) -> None:
        self.cfg = mesclar(VIDA_PADRAO, vida or {})["torcida"]
        self._acum = 0.0  # segundos já contados
        self._desde: float | None = None  # início do trecho em curso (jogo aberto e Pedro presente)
        self._ultima: float | None = None  # última ``torcida`` (qualquer origem)
        self._var: str | None = None
        self._tem_var = False

    # -- relógio ----------------------------------------------------------------------------------
    def atualizar(self, agora: float, *, jogo: bool, presente: bool) -> None:
        ativo = jogo and presente
        if ativo and self._desde is None:
            self._desde = agora
        elif not ativo and self._desde is not None:
            self._acum += max(0.0, agora - self._desde)
            self._desde = None

    def positiva(self, agora: float) -> None:
        """Saiu uma positiva: zera o relógio."""
        self._acum = 0.0
        if self._desde is not None:
            self._desde = agora

    def minutos(self, agora: float) -> float:
        corre = max(0.0, agora - self._desde) if self._desde is not None else 0.0
        return (self._acum + corre) / 60.0

    # -- variantes --------------------------------------------------------------------------------
    def variante(self, rng: random.Random | None = None) -> str | None:
        """A próxima variante: nunca a mesma da anterior (a 1ª pelo ``rng``, ou a primeira)."""
        livres = [v for v in VARIANTES if not (self._tem_var and v == self._var)] or list(VARIANTES)
        return rng.choice(livres) if rng is not None else livres[0]

    def registrar(self, agora: float, var: str | None) -> None:
        """Saiu uma ``torcida`` (do piso ou do sorteio): conta o intervalo, a variante e zera."""
        self._ultima = agora
        self._var, self._tem_var = var, True
        self.positiva(agora)

    # -- decisão ----------------------------------------------------------------------------------
    def _intervalo_ok(self, agora: float) -> bool:
        return self._ultima is None or agora - self._ultima >= self.cfg["intervalo_min"] * 60

    def _vale(self, agora: float, momento: Momento | str | None, limiar_min: float) -> bool:
        return (bool(self.cfg["liga"]) and momento == Momento.JOGANDO
                and self._intervalo_ok(agora) and self.minutos(agora) >= limiar_min)

    def forca(self, agora: float, momento: Momento | str | None) -> bool:
        """O próximo slot de passiva deve ser ``torcida``."""
        return self._vale(agora, momento, self.cfg["forca_slot_min"])

    def _tentar(self, agora: float, gov: Governador, fora: bool, ctx: dict | None,
                rng: random.Random | None) -> Escolha | None:
        p = Pedido(Tipo.GESTO, CHAVE, fora_de_slot=fora)
        if not gov.aprovar(p, agora, ctx):
            return None
        causa = f"{CAUSA}:{int(self.minutos(agora))}"
        var = self.variante(rng)
        self.registrar(agora, var)
        return Escolha(CHAVE, var, causa, float(self.cfg["delta_animo"]), fora)

    def no_slot(self, agora: float, momento: Momento | str | None, gov: Governador,
                ctx: dict | None = None, rng: random.Random | None = None) -> Escolha | None:
        """No slot de passiva: ``torcida`` forçada (≥ ``forca_slot_min``), ou ``None`` (sorteia)."""
        if not self.forca(agora, momento):
            return None
        return self._tentar(agora, gov, False, ctx, rng)

    def fora_do_slot(self, agora: float, momento: Momento | str | None, gov: Governador,
                     ctx: dict | None = None, rng: random.Random | None = None) -> Escolha | None:
        """Entre slots: ``torcida`` furando o slot (≥ ``fura_slot_min``), se o governador deixar."""
        if not self._vale(agora, momento, self.cfg["fura_slot_min"]):
            return None
        return self._tentar(agora, gov, True, ctx, rng)

    # -- estado -----------------------------------------------------------------------------------
    def exportar(self, agora: float) -> dict:
        return {"seg": self.minutos(agora) * 60.0, "ultima": self._ultima,
                "var": self._var, "tem_var": self._tem_var}

    def importar(self, dados: dict | None) -> None:
        d = dados or {}
        self._acum = float(d.get("seg", 0.0))
        self._desde = None
        self._ultima = d.get("ultima")
        self._var, self._tem_var = d.get("var"), bool(d.get("tem_var", False))
