"""Cliente mínimo do Telegram (dono: Y4.2; spec §7.2/§7.3, design §9).

- :class:`Telegram`: ``await enviar(texto)`` → ``sendMessage`` do bot para o ``chat_id``. O HTTP é
  injetado (``post(url, json) -> status``, assíncrono); sem ele usa ``httpx``. Nunca loga a URL
  (o token do bot vai nela) nem o texto; falha de rede ou status ≠ 2xx → ``False``, sem exceção.
- :func:`de_segredos`: monta a partir de ``TELEGRAM_BOT_TOKEN``/``TELEGRAM_CHAT_ID``; faltando um
  dos dois → ``None`` (quem chama só loga ``telegram_desligado``).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Final

log = logging.getLogger("ayanami.telegram")

BASE: Final = "https://api.telegram.org"
MAX_TEXTO: Final = 4000  # o limite do Telegram é 4096
PRAZO_S: Final = 10.0

Post = Callable[[str, dict[str, Any]], Awaitable[int]]


async def _post_httpx(url: str, corpo: dict[str, Any]) -> int:
    import httpx

    async with httpx.AsyncClient(timeout=PRAZO_S) as cliente:
        r = await cliente.post(url, json=corpo)
        return r.status_code


class Telegram:
    def __init__(self, token: str, chat_id: str, *, http: Post | None = None, base: str = BASE) -> None:
        self._token = token
        self.chat_id = chat_id
        self._http = http or _post_httpx
        self._base = base.rstrip("/")

    def __repr__(self) -> str:
        return f"Telegram(chat_id={self.chat_id!r})"

    async def enviar(self, texto: str) -> bool:
        url = f"{self._base}/bot{self._token}/sendMessage"
        corpo = {"chat_id": self.chat_id, "text": texto[:MAX_TEXTO], "disable_web_page_preview": True}
        try:
            status = await self._http(url, corpo)
        except Exception as e:  # noqa: BLE001 — aviso nunca derruba o job
            log.warning("telegram_falhou (%s)", type(e).__name__)
            return False
        if not 200 <= int(status) < 300:
            log.warning("telegram_status (%s)", status)
            return False
        return True


def de_segredos(segredos: Any, *, http: Post | None = None) -> Telegram | None:
    token = segredos.get("TELEGRAM_BOT_TOKEN") if segredos is not None else None
    chat = segredos.get("TELEGRAM_CHAT_ID") if segredos is not None else None
    if not token or not chat:
        return None
    return Telegram(token, chat, http=http)
