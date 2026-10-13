#!/usr/bin/env python3
"""Vigia da Ayanami no host do node 2 (Y1.3; design §11, spec §7.3; R4.4, R10.5).

Roda fora do Docker, no ``python3`` do host, só com a biblioteca padrão, a cada minuto
(``ayanami-vigia.timer``). Causas de alerta:

- ``saude``: ``GET /saude`` falhando (rede, ``503``, JSON inválido) 3 vezes seguidas;
- ``disco:<caminho>``: uso > 85% (como o ``df``: usado / (usado + livre p/ usuário));
- ``worker:<fila>``: batimento em ``workers`` mais velho que 5 min (ou nulo);
- ``snapshot:pc`` / ``snapshot:ayanami``: ``ultimo_backup`` mais velho que 36 h (ou nulo);
- ``backup_falhou``: ``/saude`` traz ``backup_falhou`` verdadeiro;
- ``restore``: ``/saude`` traz ``restore_teste.verde`` falso.

Telegram por ``TELEGRAM_BOT_TOKEN``/``TELEGRAM_CHAT_ID`` lidos do ``.env``. Anti-repetição: 1
mensagem por causa a cada 6 h, guardada em ``/opt/ayanami/dados/vigia.json`` (só marca o envio se
o Telegram aceitou). A mensagem é montada só com nomes de causa e números/datas validados: nunca
leva o token nem o corpo de uma resposta HTTP. Rede, relógio e disco são injetáveis (testes).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC = timezone.utc  # noqa: UP017 — o python3 do host pode ser 3.10

URL_SAUDE = "http://127.0.0.1:8740/saude"
TELEGRAM_API = "https://api.telegram.org"
ENV_PADRAO = Path("/opt/ayanami/.env")
ESTADO_PADRAO = Path("/opt/ayanami/dados/vigia.json")
DISCOS_PADRAO = ("/", "/opt/ayanami/dados")

FALHAS_SAUDE = 3
DISCO_LIMITE = 85.0
BATIMENTO_MAX = timedelta(minutes=5)
SNAPSHOT_MAX = timedelta(hours=36)
REPETICAO = timedelta(hours=6)
TIMEOUT = 10.0

# (método, url, corpo|None, timeout) -> (status, corpo). Exceção = falha de rede.
Http = Callable[[str, str, "bytes | None", float], "tuple[int, bytes]"]
Relogio = Callable[[], datetime]
Disco = Callable[[str], float]

_NOME_OK = re.compile(r"^[A-Za-z0-9_.\-/]{1,64}$")


def http_urllib(metodo: str, url: str, corpo: bytes | None, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=corpo, method=metodo)
    if corpo is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — URL fixa/local
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read()
        finally:
            e.close()


def agora_utc() -> datetime:
    return datetime.now(UTC)


def uso_disco(caminho: str) -> float:
    """Percentual usado como o ``df`` (blocos usados / (usados + disponíveis ao usuário))."""
    st = os.statvfs(caminho)
    usados = (st.f_blocks - st.f_bfree) * st.f_frsize
    livres = st.f_bavail * st.f_frsize
    total = usados + livres
    return 100.0 * usados / total if total else 0.0


def ler_env(caminho: Path) -> dict[str, str]:
    """``KEY=valor`` simples (comentários, ``export`` e aspas tolerados)."""
    saida: dict[str, str] = {}
    try:
        linhas = caminho.read_text(encoding="utf-8").splitlines()
    except OSError:
        return saida
    for linha in linhas:
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        chave = chave.strip().removeprefix("export ").strip()
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        saida[chave] = valor
    return saida


def _ts(valor: object) -> datetime | None:
    if not isinstance(valor, str) or not valor:
        return None
    texto = valor[:-1] + "+00:00" if valor.endswith("Z") else valor
    try:
        dt = datetime.fromisoformat(texto)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _nome(valor: object) -> str:
    texto = str(valor)
    return texto if _NOME_OK.match(texto) else "?"


def _idade(agora: datetime, quando: datetime | None) -> str:
    if quando is None:
        return "sem registro"
    minutos = int((agora - quando).total_seconds() // 60)
    return f"há {minutos // 60} h" if minutos >= 120 else f"há {minutos} min"


@dataclass
class Estado:
    falhas_saude: int = 0
    enviados: dict[str, str] = field(default_factory=dict)

    @classmethod
    def carregar(cls, caminho: Path) -> Estado:
        try:
            dados = json.loads(caminho.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(dados, dict):
            return cls()
        env = dados.get("enviados")
        return cls(
            falhas_saude=int(dados.get("falhas_saude") or 0),
            enviados={str(k): str(v) for k, v in env.items()} if isinstance(env, dict) else {},
        )

    def salvar(self, caminho: Path) -> None:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        tmp = caminho.with_name(caminho.name + ".tmp")
        tmp.write_text(
            json.dumps({"falhas_saude": self.falhas_saude, "enviados": self.enviados},
                       ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, caminho)


def buscar_saude(http: Http, url: str) -> dict | None:
    """JSON da ``/saude`` com ``200``; qualquer outra coisa é falha (``None``)."""
    try:
        status, corpo = http("GET", url, None, TIMEOUT)
    except Exception:  # noqa: BLE001 — rede fora conta como falha
        return None
    if status != 200:
        return None
    try:
        dados = json.loads(corpo)
    except ValueError:
        return None
    return dados if isinstance(dados, dict) else None


def causas_saude(saude: dict, agora: datetime) -> list[tuple[str, str]]:
    causas: list[tuple[str, str]] = []
    workers = saude.get("workers")
    if isinstance(workers, dict):
        for fila in sorted(workers, key=str):
            visto = _ts(workers[fila])
            if visto is None or agora - visto > BATIMENTO_MAX:
                nome = _nome(fila)
                causas.append((f"worker:{nome}", f"worker {nome} sem batimento ({_idade(agora, visto)})"))
    ultimo = saude.get("ultimo_backup")
    if isinstance(ultimo, dict):
        for origem in ("pc", "ayanami"):
            quando = _ts(ultimo.get(origem))
            if quando is None or agora - quando > SNAPSHOT_MAX:
                causas.append((f"snapshot:{origem}",
                               f"backup {origem} atrasado > 36 h ({_idade(agora, quando)})"))
    if saude.get("backup_falhou") is True:
        causas.append(("backup_falhou", "job de backup falhou"))
    restore = saude.get("restore_teste")
    if isinstance(restore, dict) and restore.get("verde") is False:
        causas.append(("restore", "restore de teste VERMELHO"))
    return causas


def causas_disco(disco: Disco, caminhos: Iterable[str]) -> list[tuple[str, str]]:
    causas: list[tuple[str, str]] = []
    for caminho in caminhos:
        try:
            uso = float(disco(caminho))
        except OSError:
            continue
        if uso > DISCO_LIMITE:
            nome = _nome(caminho)
            causas.append((f"disco:{nome}", f"disco {nome} em {uso:.0f}% (> 85%)"))
    return causas


def enviar_telegram(http: Http, token: str, chat_id: str, texto: str, base: str = TELEGRAM_API) -> bool:
    corpo = urllib.parse.urlencode({"chat_id": chat_id, "text": texto}).encode()
    try:
        status, _ = http("POST", f"{base}/bot{token}/sendMessage", corpo, TIMEOUT)
    except Exception as e:  # noqa: BLE001 — nunca loga a URL (tem o token)
        print(f"vigia: telegram falhou ({type(e).__name__})", file=sys.stderr)
        return False
    if status != 200:
        print(f"vigia: telegram respondeu {status}", file=sys.stderr)
        return False
    return True


def rodar(
    *,
    env: dict[str, str],
    estado_path: Path,
    http: Http = http_urllib,
    relogio: Relogio = agora_utc,
    disco: Disco = uso_disco,
    url_saude: str = URL_SAUDE,
    discos: Iterable[str] = DISCOS_PADRAO,
    telegram_base: str = TELEGRAM_API,
) -> list[str]:
    """Uma passada do vigia. Devolve as causas cujo alerta foi enviado agora."""
    agora = relogio()
    estado = Estado.carregar(estado_path)
    causas: list[tuple[str, str]] = []

    saude = buscar_saude(http, url_saude)
    if saude is None:
        estado.falhas_saude += 1
        if estado.falhas_saude >= FALHAS_SAUDE:
            causas.append(("saude", f"/saude falhando ({estado.falhas_saude}x seguidas)"))
    else:
        estado.falhas_saude = 0
        causas.extend(causas_saude(saude, agora))
    causas.extend(causas_disco(disco, discos))

    token = env.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = env.get("TELEGRAM_CHAT_ID", "")
    enviadas: list[str] = []
    for chave, texto in causas:
        ultimo = _ts(estado.enviados.get(chave))
        if ultimo is not None and agora - ultimo < REPETICAO:
            continue
        if not token or not chat_id:
            print("vigia: TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID ausentes no .env", file=sys.stderr)
            break
        if enviar_telegram(http, token, chat_id, f"⚠ Ayanami: {texto}", telegram_base):
            estado.enviados[chave] = agora.isoformat()
            enviadas.append(chave)
    estado.salvar(estado_path)
    return enviadas


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ayanami-vigia", description=__doc__.splitlines()[0])
    ap.add_argument("--env", type=Path, default=ENV_PADRAO)
    ap.add_argument("--estado", type=Path, default=ESTADO_PADRAO)
    ap.add_argument("--url", default=URL_SAUDE)
    ap.add_argument("--disco", action="append", default=None, help="caminho a medir (repetível)")
    args = ap.parse_args(argv)
    env = ler_env(args.env)
    enviadas = rodar(env=env, estado_path=args.estado, url_saude=args.url,
                     discos=args.disco or DISCOS_PADRAO)
    for chave in enviadas:
        print(f"vigia: alerta enviado ({chave})")
    return 0 if env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID") else 1


if __name__ == "__main__":
    sys.exit(main())
