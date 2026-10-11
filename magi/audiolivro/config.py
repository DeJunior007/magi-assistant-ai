"""Seção ``[audiolivro]`` e tarefas do livro (tarefa A0.1; spec §6, decisões D1–D6 de 2026-10-10).

Tudo tem padrão: sem ``[audiolivro]`` o modo funciona com os valores da spec §6.

- D1/D5: o livro é **sempre Kokoro** e **sempre na voz dela**: ``voz_dela``/``idioma_dela`` vêm do
  ``[tasks].tts`` quando ele é Kokoro; senão do padrão Kokoro do ``[speech] language``.
  ``tts_livro`` devolve a tarefa de TTS do livro (nunca um provedor pago).
- D2: ``tarefa_marca`` só aceita provedor local (``qwen``); outro provedor → ``None`` (só regras).
- D3: ``pasta`` padrão ``~/Livros`` (``garantir_pasta`` cria quando a biblioteca for usada).

Caminhos de estado/cache seguem ``$XDG_STATE_HOME``/``$XDG_CACHE_HOME`` (o ``conftest`` dos testes
os aponta para ``tmp_path``).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from magi.common.config import Config, ConfigError, TaskConfig

log = logging.getLogger(__name__)

MARCACOES = ("qwen", "regras")
MUSICAS = ("pausa", "duck")
TAREFA_MARCA = "audiolivro_marca"
TAREFA_TTS_LIVRO = "audiolivro_tts"
#: Provedores aceitos na marcação (D2: só local, nunca LLM pago).
PROVEDORES_MARCA_LOCAIS = frozenset({"qwen"})
#: Voz Kokoro padrão por idioma dela (quando o ``[tasks].tts`` não é Kokoro).
VOZ_PADRAO = {"pt-br": "pf_dora", "en-gb": "bf_isabella", "en": "af_heart", "en-us": "af_heart"}
MODELO_KOKORO = "kokoro-v1.0"
MARCA_PADRAO = TaskConfig(
    name=TAREFA_MARCA, provider="qwen", model="qwen-learning", options={"timeout_s": 60}
)


def _xdg(var: str, padrao: str) -> Path:
    return Path(os.environ.get(var) or padrao).expanduser()


@dataclass(frozen=True)
class ConfigAudiolivro:
    """``[audiolivro]`` (spec §6). ``vozes`` = grupos por idioma dela (spec §3):
    ``{"en-gb": {"f": [...], "m": [...], "jovem": [...], "idoso": [...]}}``."""

    pasta: Path = field(default_factory=lambda: Path("~/Livros").expanduser())
    marcacao: str = "qwen"
    musica: str = "pausa"
    chars_por_pagina: int = 1800
    chars_por_minuto: int = 900
    parar_apos_capitulos: int = 0
    retomar_apos_comando: bool = True
    pausa_expira_min: int = 30
    qwen_container: str = "magi-qwen"
    qwen_url: str = "http://127.0.0.1:11435"
    qwen_start_timeout_s: int = 90
    vozes: dict[str, dict[str, tuple[str, ...]]] = field(default_factory=dict)
    estado_dir: Path = field(default_factory=lambda: _xdg("XDG_STATE_HOME", "~/.local/state") / "magi")
    cache_dir: Path = field(
        default_factory=lambda: _xdg("XDG_CACHE_HOME", "~/.cache") / "magi" / "audiolivro"
    )

    @property
    def marcador_path(self) -> Path:
        return self.estado_dir / "audiolivro.json"

    @property
    def registro_path(self) -> Path:
        return self.estado_dir / "audiolivro.jsonl"

    @property
    def elenco_dir(self) -> Path:
        return self.estado_dir / "audiolivro" / "elenco"

    def garantir_pasta(self) -> Path:
        """Cria a pasta da biblioteca se faltar (D3) e a devolve."""
        self.pasta.mkdir(parents=True, exist_ok=True)
        return self.pasta


def _int(sec: dict[str, Any], k: str, padrao: int, minimo: int) -> int:
    v = sec.get(k, padrao)
    if isinstance(v, bool) or not isinstance(v, int) or v < minimo:
        raise ConfigError(f"audiolivro.{k} deve ser inteiro ≥ {minimo}")
    return v


def _str(sec: dict[str, Any], k: str, padrao: str, escolhas: tuple[str, ...] | None = None) -> str:
    v = sec.get(k, padrao)
    if not isinstance(v, str):
        raise ConfigError(f"audiolivro.{k} deve ser texto")
    if escolhas is not None and v not in escolhas:
        raise ConfigError(f"audiolivro.{k} deve ser um de {', '.join(escolhas)}")
    return v


def _vozes(sec: dict[str, Any]) -> dict[str, dict[str, tuple[str, ...]]]:
    raw = sec.get("vozes") or {}
    if not isinstance(raw, dict):
        raise ConfigError("audiolivro.vozes deve ser uma tabela")
    out: dict[str, dict[str, tuple[str, ...]]] = {}
    for idioma, grupos in raw.items():
        if not isinstance(grupos, dict):
            raise ConfigError(f"audiolivro.vozes.{idioma} deve ser uma tabela")
        g: dict[str, tuple[str, ...]] = {}
        for nome, lista in grupos.items():
            if not isinstance(lista, list) or not all(isinstance(x, str) and x for x in lista):
                raise ConfigError(f"audiolivro.vozes.{idioma}.{nome} deve ser lista de vozes")
            g[str(nome)] = tuple(lista)
        out[str(idioma).lower()] = g
    return out


def parse_audiolivro(raw: dict[str, Any]) -> ConfigAudiolivro:
    """``ConfigAudiolivro`` a partir do TOML inteiro (lê só ``[audiolivro]``)."""
    sec = raw.get("audiolivro") or {}
    if not isinstance(sec, dict):
        raise ConfigError("audiolivro deve ser uma tabela")
    d = ConfigAudiolivro()
    retomar = sec.get("retomar_apos_comando", d.retomar_apos_comando)
    if not isinstance(retomar, bool):
        raise ConfigError("audiolivro.retomar_apos_comando deve ser true/false")
    return ConfigAudiolivro(
        pasta=Path(_str(sec, "pasta", str(d.pasta))).expanduser(),
        marcacao=_str(sec, "marcacao", d.marcacao, MARCACOES),
        musica=_str(sec, "musica", d.musica, MUSICAS),
        chars_por_pagina=_int(sec, "chars_por_pagina", d.chars_por_pagina, 1),
        chars_por_minuto=_int(sec, "chars_por_minuto", d.chars_por_minuto, 1),
        parar_apos_capitulos=_int(sec, "parar_apos_capitulos", d.parar_apos_capitulos, 0),
        retomar_apos_comando=retomar,
        pausa_expira_min=_int(sec, "pausa_expira_min", d.pausa_expira_min, 1),
        qwen_container=_str(sec, "qwen_container", d.qwen_container),
        qwen_url=_str(sec, "qwen_url", d.qwen_url).rstrip("/"),
        qwen_start_timeout_s=_int(sec, "qwen_start_timeout_s", d.qwen_start_timeout_s, 1),
        vozes=_vozes(sec),
    )


def audiolivro_config(config: Config) -> ConfigAudiolivro:
    """Seção ``[audiolivro]`` do ``Config`` já carregado."""
    return parse_audiolivro(config.raw)


def idioma_dela(config: Config) -> str:
    """Idioma da voz dela (D5): ``lang`` do ``[tasks].tts`` Kokoro, senão ``[speech] language``."""
    tts = config.tasks.get("tts")
    if tts is not None and tts.provider == "kokoro" and tts.options.get("lang"):
        return str(tts.options["lang"]).lower()
    speech = config.raw.get("speech") or {}
    lang = speech.get("language") if isinstance(speech, dict) else None
    return str(lang or "pt-br").lower()


def voz_dela(config: Config) -> str:
    """Voz Kokoro dela (D1/D5): a do ``[tasks].tts`` se for Kokoro; senão a padrão do idioma."""
    tts = config.tasks.get("tts")
    if tts is not None and tts.provider == "kokoro" and tts.options.get("voice"):
        return str(tts.options["voice"])
    return VOZ_PADRAO.get(idioma_dela(config), VOZ_PADRAO["pt-br"])


def tts_livro(config: Config) -> TaskConfig:
    """Tarefa de TTS do livro: o ``[tasks].tts`` se já é Kokoro; senão um Kokoro só para o livro
    (D1: o livro nunca usa TTS pago)."""
    tts = config.tasks.get("tts")
    if tts is not None and tts.provider == "kokoro":
        return tts
    if tts is not None:
        log.info("audiolivro: [tasks].tts é %s; o livro usa o Kokoro (D1)", tts.provider)
    return TaskConfig(
        name=TAREFA_TTS_LIVRO,
        provider="kokoro",
        model=MODELO_KOKORO,
        options={"voice": voz_dela(config), "lang": idioma_dela(config)},
    )


def tarefa_marca(config: Config, cfg: ConfigAudiolivro | None = None) -> TaskConfig | None:
    """Tarefa do refino (A1.3, D2): ``[tasks].audiolivro_marca`` ou o padrão Qwen local.
    ``None`` = só regras (``marcacao = "regras"`` ou provedor não local, recusado com log)."""
    cfg = cfg or audiolivro_config(config)
    if cfg.marcacao != "qwen":
        return None
    t = config.tasks.get(TAREFA_MARCA, MARCA_PADRAO)
    if t.provider not in PROVEDORES_MARCA_LOCAIS:
        log.warning(
            "audiolivro: tasks.%s com provedor %r recusado (só Qwen local, D2); só regras",
            TAREFA_MARCA,
            t.provider,
        )
        return None
    return t
