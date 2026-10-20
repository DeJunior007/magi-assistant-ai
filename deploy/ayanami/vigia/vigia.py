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

Servidor e Minecraft (Y1.3b; o node 2 é dividido com o Minecraft, núcleos 0-5 dele e 6-7 da
Ayanami), quando ``rodar`` recebe um ``ConfServidor`` (o ``main`` sempre passa, salvo
``--sem-servidor``):

- ``cpu:minecraft``: núcleos do Minecraft > 95% por 5 leituras seguidas (``/proc/stat``);
- ``ram``: ``MemAvailable`` < 1 GiB; ``swap``: swap usado > 6 GiB (``/proc/meminfo``);
- ``minecraft:parado``: container fora de ``running``; ``minecraft:reiniciou``: ``RestartCount``
  subiu desde a última leitura (``docker inspect``). Container inexistente não é erro;
- ``minecraft:tps``: TPS < 15 por 3 leituras (RCON em 127.0.0.1:25575, ``spark tps`` se o Spark
  existir; sem Spark só ``list``). Senha ``RCON_PASSWORD`` de ``/opt/minecraft/.env``.

Tudo vai num resumo JSON atômico em ``/opt/ayanami/dados/servidor.json`` (para a Ayanami responder
"como está o servidor?"). Limites/nomes configuráveis no ``.env`` da Ayanami (``VIGIA_*``).

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
import socket
import struct
import subprocess
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

# Servidor/Minecraft (Y1.3b) — padrões; cada um tem um ``VIGIA_*`` no .env (ConfServidor.do_env).
MC_CONTAINER = "minecraft"           # VIGIA_MC_CONTAINER
MC_ENV = Path("/opt/minecraft/.env")  # VIGIA_MC_ENV (lê RCON_PASSWORD)
RCON_HOST = "127.0.0.1"              # VIGIA_RCON_HOST
RCON_PORTA = 25575                   # VIGIA_RCON_PORTA
RESUMO_PADRAO = Path("/opt/ayanami/dados/servidor.json")  # VIGIA_RESUMO
NUCLEOS_MC = "0-5"                   # VIGIA_NUCLEOS_MC
NUCLEOS_AYANAMI = "6-7"              # VIGIA_NUCLEOS_AYANAMI
CPU_LIMITE = 95.0                    # VIGIA_CPU_LIMITE (%)
CPU_LEITURAS = 5                     # VIGIA_CPU_LEITURAS
RAM_MIN_GIB = 1.0                    # VIGIA_RAM_MIN_GIB
SWAP_MAX_GIB = 6.0                   # VIGIA_SWAP_MAX_GIB
TPS_MIN = 15.0                       # VIGIA_TPS_MIN
TPS_LEITURAS = 3                     # VIGIA_TPS_LEITURAS
RCON_TIMEOUT = 5.0

# (método, url, corpo|None, timeout) -> (status, corpo). Exceção = falha de rede.
Http = Callable[[str, str, "bytes | None", float], "tuple[int, bytes]"]
Relogio = Callable[[], datetime]
Disco = Callable[[str], float]
# argv -> (código de saída, stdout, stderr). FileNotFoundError = docker ausente no host.
Docker = Callable[[list[str]], "tuple[int, str, str]"]
# (host, porta, senha, comandos, timeout) -> respostas (uma por comando). Exceção = RCON fora.
Rcon = Callable[[str, int, str, "list[str]", float], "list[str]"]

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
    servidor: dict = field(default_factory=dict)  # Y1.3b: amostra de CPU, contadores, RestartCount

    @classmethod
    def carregar(cls, caminho: Path) -> Estado:
        try:
            dados = json.loads(caminho.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(dados, dict):
            return cls()
        env = dados.get("enviados")
        srv = dados.get("servidor")
        return cls(
            falhas_saude=int(dados.get("falhas_saude") or 0),
            enviados={str(k): str(v) for k, v in env.items()} if isinstance(env, dict) else {},
            servidor=srv if isinstance(srv, dict) else {},
        )

    def salvar(self, caminho: Path) -> None:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        _gravar_atomico(caminho, {"falhas_saude": self.falhas_saude, "enviados": self.enviados,
                                  "servidor": self.servidor})


def _gravar_atomico(caminho: Path, dados: dict) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_name(caminho.name + ".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, sort_keys=True), encoding="utf-8")
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


# ---- servidor e Minecraft (Y1.3b) ----

GIB = 1024 ** 3
_COR = re.compile(r"§.")
_LIST = re.compile(r"There are (\d+) (?:of a max of|out of maximum|/) ?(\d+) players online\.?:?(.*)",
                   re.IGNORECASE | re.DOTALL)
_NUM = re.compile(r"\d+(?:\.\d+)?")


def docker_subprocess(argv: list[str]) -> tuple[int, str, str]:
    r = subprocess.run(argv, capture_output=True, text=True, timeout=20, check=False)  # noqa: S603
    return r.returncode, r.stdout, r.stderr


def _rcon_pacote(sock: socket.socket, rid: int, tipo: int, corpo: str) -> None:
    dados = struct.pack("<ii", rid, tipo) + corpo.encode("utf-8") + b"\x00\x00"
    sock.sendall(struct.pack("<i", len(dados)) + dados)


def _rcon_ler(sock: socket.socket) -> tuple[int, int, str]:
    def exato(n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            parte = sock.recv(n - len(buf))
            if not parte:
                raise ConnectionError("rcon fechou")
            buf += parte
        return buf

    (tam,) = struct.unpack("<i", exato(4))
    if not 10 <= tam <= 1 << 20:
        raise ValueError("pacote rcon inválido")
    dados = exato(tam)
    rid, tipo = struct.unpack("<ii", dados[:8])
    return rid, tipo, dados[8:-2].decode("utf-8", "replace")


def rcon_socket(host: str, porta: int, senha: str, comandos: list[str], timeout: float) -> list[str]:
    """Protocolo RCON (Source/Minecraft): login tipo 3, comando tipo 2, resposta tipo 0."""
    with socket.create_connection((host, porta), timeout=timeout) as sock:
        sock.settimeout(timeout)
        _rcon_pacote(sock, 1, 3, senha)
        rid, _, _ = _rcon_ler(sock)
        if rid == -1:
            raise PermissionError("rcon recusou a senha")
        respostas = []
        for i, cmd in enumerate(comandos, start=2):
            _rcon_pacote(sock, i, 2, cmd)
            respostas.append(_rcon_ler(sock)[2])
        return respostas


def _nucleos(texto: str) -> list[int]:
    saida: list[int] = []
    for parte in texto.split(","):
        parte = parte.strip()
        if "-" in parte:
            a, b = parte.split("-", 1)
            saida.extend(range(int(a), int(b) + 1))
        elif parte:
            saida.append(int(parte))
    return saida


@dataclass
class ConfServidor:
    proc: Path = Path("/proc")
    container: str = MC_CONTAINER
    mc_env: Path = MC_ENV
    rcon_host: str = RCON_HOST
    rcon_porta: int = RCON_PORTA
    resumo: Path = RESUMO_PADRAO
    nucleos_mc: str = NUCLEOS_MC
    nucleos_ayanami: str = NUCLEOS_AYANAMI
    cpu_limite: float = CPU_LIMITE
    cpu_leituras: int = CPU_LEITURAS
    ram_min_gib: float = RAM_MIN_GIB
    swap_max_gib: float = SWAP_MAX_GIB
    tps_min: float = TPS_MIN
    tps_leituras: int = TPS_LEITURAS
    docker: Docker = docker_subprocess
    rcon: Rcon = rcon_socket

    @classmethod
    def do_env(cls, env: dict[str, str], **extra: object) -> ConfServidor:
        conv = {"container": ("VIGIA_MC_CONTAINER", str), "mc_env": ("VIGIA_MC_ENV", Path),
                "rcon_host": ("VIGIA_RCON_HOST", str), "rcon_porta": ("VIGIA_RCON_PORTA", int),
                "resumo": ("VIGIA_RESUMO", Path), "nucleos_mc": ("VIGIA_NUCLEOS_MC", str),
                "nucleos_ayanami": ("VIGIA_NUCLEOS_AYANAMI", str),
                "cpu_limite": ("VIGIA_CPU_LIMITE", float), "cpu_leituras": ("VIGIA_CPU_LEITURAS", int),
                "ram_min_gib": ("VIGIA_RAM_MIN_GIB", float),
                "swap_max_gib": ("VIGIA_SWAP_MAX_GIB", float),
                "tps_min": ("VIGIA_TPS_MIN", float), "tps_leituras": ("VIGIA_TPS_LEITURAS", int)}
        kw: dict[str, object] = {}
        for campo, (chave, tipo) in conv.items():
            if env.get(chave):
                try:
                    kw[campo] = tipo(env[chave])
                except ValueError:
                    print(f"vigia: {chave} inválido, usando o padrão", file=sys.stderr)
        kw.update(extra)
        return cls(**kw)  # type: ignore[arg-type]


def ler_stat(proc: Path) -> dict[str, list[int]]:
    """``cpuN`` -> [total, ocioso] (ocioso = idle + iowait; total sem guest, já contido em user)."""
    saida: dict[str, list[int]] = {}
    for linha in (proc / "stat").read_text(encoding="utf-8").splitlines():
        partes = linha.split()
        if partes and partes[0].startswith("cpu") and partes[0] != "cpu":
            v = [int(x) for x in partes[1:9]] + [0] * (8 - len(partes[1:9]))
            saida[partes[0]] = [sum(v), v[3] + v[4]]
    return saida


def uso_grupo(antes: dict, depois: dict[str, list[int]], nucleos: list[int]) -> float | None:
    dt = docio = 0
    for n in nucleos:
        a, d = antes.get(f"cpu{n}"), depois.get(f"cpu{n}")
        if not isinstance(a, list) or len(a) != 2 or d is None:
            continue
        dt += d[0] - a[0]
        docio += d[1] - a[1]
    return round(100.0 * (dt - docio) / dt, 1) if dt > 0 else None


def ler_meminfo(proc: Path) -> dict[str, int]:
    saida: dict[str, int] = {}
    for linha in (proc / "meminfo").read_text(encoding="utf-8").splitlines():
        chave, _, resto = linha.partition(":")
        partes = resto.split()
        if partes and partes[0].isdigit():
            saida[chave.strip()] = int(partes[0]) * 1024
    return saida


def inspecionar(conf: ConfServidor) -> dict:
    """``{"status": "ausente"}`` | ``{"status": "erro"}`` | ``{"status", "restart_count", ...}``."""
    try:
        codigo, out, err = conf.docker(["docker", "inspect", "--type", "container", conf.container])
    except (OSError, subprocess.SubprocessError):
        return {"status": "erro"}
    if codigo != 0:
        return {"status": "ausente"} if "no such" in err.lower() else {"status": "erro"}
    try:
        info = json.loads(out)[0]
        estado = info["State"]
        return {"status": _nome(estado.get("Status")), "restart_count": int(info.get("RestartCount") or 0),
                "iniciado": _nome(str(estado.get("StartedAt", ""))[:19])}
    except (ValueError, KeyError, IndexError, TypeError):
        return {"status": "erro"}


def consultar_rcon(conf: ConfServidor) -> dict:
    senha = ler_env(conf.mc_env).get("RCON_PASSWORD", "")
    if not senha:
        return {"rcon": "sem_senha"}
    try:
        r_list, r_tps = conf.rcon(conf.rcon_host, conf.rcon_porta, senha, ["list", "spark tps"], RCON_TIMEOUT)
    except Exception as e:  # noqa: BLE001 — nunca ecoa a resposta nem a senha
        return {"rcon": f"erro ({type(e).__name__})"}
    saida: dict = {"rcon": "ok", "jogadores": None, "max_jogadores": None, "nomes": [],
                   "spark": False, "tps": None}
    m = _LIST.search(_COR.sub("", r_list))
    if m:
        saida["jogadores"], saida["max_jogadores"] = int(m.group(1)), int(m.group(2))
        saida["nomes"] = [_nome(n.strip()) for n in m.group(3).split(",") if n.strip()][:50]
    tps = _COR.sub("", r_tps)
    linhas = tps.splitlines()
    for i, linha in enumerate(linhas):
        if "tps from last" in linha.lower() and i + 1 < len(linhas):
            nums = [float(x) for x in _NUM.findall(linhas[i + 1])]
            if nums:
                saida["spark"] = True
                saida["tps"] = nums[2] if len(nums) > 2 else nums[0]  # média de 1 min
                saida["tps_todos"] = nums[:5]
            break
    return saida


def checar_servidor(conf: ConfServidor, estado: dict, agora: datetime) -> tuple[list[tuple[str, str]], dict]:
    """Lê /proc, docker e RCON; atualiza ``estado`` (contadores) e devolve (causas, resumo)."""
    causas: list[tuple[str, str]] = []
    resumo: dict = {"ts": agora.isoformat()}

    try:
        stat = ler_stat(conf.proc)
    except (OSError, ValueError):
        stat = None
    if stat is not None:
        antes = estado.get("cpu_amostra") if isinstance(estado.get("cpu_amostra"), dict) else {}
        uso_mc = uso_grupo(antes, stat, _nucleos(conf.nucleos_mc))
        uso_ay = uso_grupo(antes, stat, _nucleos(conf.nucleos_ayanami))
        estado["cpu_amostra"] = stat
        resumo["cpu"] = {"minecraft": {"nucleos": conf.nucleos_mc, "uso": uso_mc},
                         "ayanami": {"nucleos": conf.nucleos_ayanami, "uso": uso_ay}}
        if uso_mc is not None and uso_mc > conf.cpu_limite:
            estado["cpu_alto"] = int(estado.get("cpu_alto") or 0) + 1
        elif uso_mc is not None:
            estado["cpu_alto"] = 0
        if int(estado.get("cpu_alto") or 0) >= conf.cpu_leituras:
            causas.append(("cpu:minecraft", f"núcleos {conf.nucleos_mc} (Minecraft) acima de "
                           f"{conf.cpu_limite:.0f}% há {estado['cpu_alto']} leituras"))
    else:
        resumo["cpu"] = None
    try:
        partes = (conf.proc / "loadavg").read_text(encoding="utf-8").split()
        resumo["load"] = [float(x) for x in partes[:3]]
    except (OSError, ValueError):
        resumo["load"] = None
    try:
        mem = ler_meminfo(conf.proc)
    except (OSError, ValueError):
        mem = {}
    if "MemAvailable" in mem:
        disp = mem["MemAvailable"] / GIB
        swap_usado = (mem.get("SwapTotal", 0) - mem.get("SwapFree", 0)) / GIB
        resumo["ram"] = {"total_gib": round(mem.get("MemTotal", 0) / GIB, 2),
                         "disponivel_gib": round(disp, 2)}
        resumo["swap"] = {"total_gib": round(mem.get("SwapTotal", 0) / GIB, 2),
                          "usado_gib": round(swap_usado, 2)}
        if disp < conf.ram_min_gib:
            causas.append(("ram", f"RAM disponível em {disp:.2f} GiB (< {conf.ram_min_gib:g} GiB)"))
        if swap_usado > conf.swap_max_gib:
            causas.append(("swap", f"swap usado em {swap_usado:.1f} GiB (> {conf.swap_max_gib:g} GiB)"))
    else:
        resumo["ram"] = resumo["swap"] = None

    mc = inspecionar(conf)
    if mc["status"] == "ausente":
        resumo["minecraft"] = "ausente"
        estado.pop("mc_restart_count", None)
        estado["tps_baixo"] = 0
    else:
        anterior = estado.get("mc_restart_count")
        if "restart_count" in mc:
            if isinstance(anterior, int) and mc["restart_count"] > anterior:
                causas.append(("minecraft:reiniciou", f"container {_nome(conf.container)} reiniciou "
                               f"(RestartCount {anterior} → {mc['restart_count']})"))
            estado["mc_restart_count"] = mc["restart_count"]
        if mc["status"] not in ("running", "erro"):
            causas.append(("minecraft:parado", f"container {_nome(conf.container)} {mc['status']}"))
        if mc["status"] == "running":
            mc.update(consultar_rcon(conf))
            tps = mc.get("tps")
            if isinstance(tps, float):
                estado["tps_baixo"] = int(estado.get("tps_baixo") or 0) + 1 if tps < conf.tps_min else 0
            else:
                estado["tps_baixo"] = 0  # sem Spark/RCON: não há TPS para contar
            if int(estado.get("tps_baixo") or 0) >= conf.tps_leituras:
                causas.append(("minecraft:tps", f"TPS do Minecraft em {tps} (< {conf.tps_min:g}) "
                               f"há {estado['tps_baixo']} leituras"))
        else:
            estado["tps_baixo"] = 0
        resumo["minecraft"] = mc
    resumo["alertas"] = [chave for chave, _ in causas]
    return causas, resumo


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
    servidor: ConfServidor | None = None,
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
    if servidor is not None:
        causas_srv, resumo = checar_servidor(servidor, estado.servidor, agora)
        causas.extend(causas_srv)
        try:
            _gravar_atomico(servidor.resumo, resumo)
        except OSError as e:
            print(f"vigia: resumo do servidor não gravado ({type(e).__name__})", file=sys.stderr)

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
    ap.add_argument("--sem-servidor", action="store_true",
                    help="não olha CPU/RAM/swap nem o Minecraft (Y1.3b)")
    args = ap.parse_args(argv)
    env = ler_env(args.env)
    servidor = None if args.sem_servidor else ConfServidor.do_env(env)
    enviadas = rodar(env=env, estado_path=args.estado, url_saude=args.url,
                     discos=args.disco or DISCOS_PADRAO, servidor=servidor)
    for chave in enviadas:
        print(f"vigia: alerta enviado ({chave})")
    return 0 if env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID") else 1


if __name__ == "__main__":
    sys.exit(main())
