"""Pareamento do celular por voz (ayanami-central Y6.6b): "Condessa, pareia o celular".

``celular.parear`` chama ``magi.elo.parear.pedir_codigo`` com o sink de avisos do core: o código
de 6 dígitos aparece só no card "Código de pareamento 123 456" do HUD. A fala é curta e fixa; o
código nunca vai para a fala nem para log. Sem ``[ayanami]`` no config, responde que a Ayanami
não está configurada (o handler é registrado sempre, para a frase não cair no agente).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import httpx

from magi.common.contracts import ActionRequest, ActionResult, Expression, IntentId

log = logging.getLogger(__name__)

SAY_CODIGO_NA_TELA = "Código na tela, vale 5 minutos."  # o código vale 5 min (spec §2.2)
SAY_SEM_AYANAMI = "A Ayanami não está configurada."
SAY_SEM_TOKEN = "Falta o token do PC para a Ayanami."
SAY_AYANAMI_FORA = "Não consegui falar com a Ayanami."


class CelularActions:
    """``url``: ``[ayanami] url`` (``None`` = sem Ayanami). ``token``: lido na hora (keyring).
    ``avisos``: devolve o ``AvisosAyanami`` do core na hora (o sink da proatividade sobe depois
    do ``assemble``)."""

    intents = frozenset({IntentId.CELULAR_PAREAR.value})

    def __init__(
        self,
        url: str | None,
        *,
        token: Callable[[], str | None] | None = None,
        avisos: Callable[[], Any] | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.url = url
        self._token = token
        self._avisos = avisos
        self._http = http

    @classmethod
    def de_config(cls, config: Any, core: Any = None, **kw: Any) -> CelularActions:
        from magi.elo.credenciais import url_ayanami

        def avisos() -> Any:
            from magi.core.proactive.ayanami import AvisosAyanami

            return AvisosAyanami(getattr(core, "proactive", None))

        kw.setdefault("avisos", avisos)
        return cls(url_ayanami(config), **kw)

    async def run(self, req: ActionRequest) -> ActionResult:
        if self.url is None:
            return ActionResult(ok=False, speech=SAY_SEM_AYANAMI)
        if self._token is None:
            from magi.elo.credenciais import token_pc

            self._token = token_pc
        try:
            tok = self._token()
        except Exception as e:  # noqa: BLE001 - keyring trancado etc.; segue como sem token
            log.warning("celular: token do PC ilegível (%s)", type(e).__name__)
            tok = None
        if not tok:
            return ActionResult(ok=False, speech=SAY_SEM_TOKEN)
        from magi.elo.parear import ErroPareamento, pedir_codigo

        avisos = self._avisos() if self._avisos is not None else None
        try:
            await pedir_codigo(self.url, tok, http=self._http, avisos=avisos)
        except ErroPareamento as e:  # a mensagem não tem segredo nem código
            log.warning("celular: pareamento falhou: %s", e)
            return ActionResult(ok=False, speech=SAY_AYANAMI_FORA, expression=Expression.CONFUSED)
        return ActionResult(ok=True, speech=SAY_CODIGO_NA_TELA)
