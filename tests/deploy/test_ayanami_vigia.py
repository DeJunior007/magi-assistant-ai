"""Vigia da Ayanami (Y1.3, spec §7.3). Rede, relógio e disco falsos; nada toca systemd nem Telegram."""

from __future__ import annotations

import configparser
import importlib.util
import json
import sys
import threading
import urllib.parse
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
VIGIA = REPO / "deploy" / "ayanami" / "vigia"

_spec = importlib.util.spec_from_file_location("ayanami_vigia", VIGIA / "vigia.py")
assert _spec and _spec.loader
vigia = importlib.util.module_from_spec(_spec)
sys.modules["ayanami_vigia"] = vigia
_spec.loader.exec_module(vigia)

TOKEN = "123456:TOKEN-FALSO-DE-TESTE"
CHAT = "4242"
ENV = {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": CHAT}
T0 = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
SEGREDO_NO_CORPO = "corpo-secreto-da-resposta"


def _z(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def saude_ok(agora: datetime = T0) -> dict:
    return {
        "ok": True,
        "banco": "ok",
        "fila": {"rapida": {"todo": 0, "doing": 0, "failed_24h": 0}},
        "workers": {"rapido": _z(agora - timedelta(seconds=30)), "agendado": _z(agora)},
        "ultimo_backup": {"pc": _z(agora - timedelta(hours=10)), "ayanami": _z(agora - timedelta(hours=2)),
                          "restic": _z(agora)},
        "online": {"pc": True, "casa": False, "celulares": 1},
        "faltando": [],
    }


class Rede:
    """``/saude`` configurável + Telegram falso que registra as mensagens."""

    def __init__(self, saude: dict | None = None, status: int = 200, telegram_status: int = 200) -> None:
        self.saude = saude if saude is not None else saude_ok()
        self.status = status
        self.cair = False
        self.telegram_status = telegram_status
        self.mensagens: list[str] = []
        self.urls: list[str] = []

    def __call__(self, metodo: str, url: str, corpo: bytes | None, timeout: float) -> tuple[int, bytes]:
        self.urls.append(url)
        if url.endswith("/saude"):
            if self.cair:
                raise OSError("conexão recusada")
            if self.status != 200:
                return self.status, json.dumps({"ok": False, "x": SEGREDO_NO_CORPO}).encode()
            return 200, json.dumps(self.saude).encode()
        assert metodo == "POST" and url == f"{vigia.TELEGRAM_API}/bot{TOKEN}/sendMessage"
        dados = urllib.parse.parse_qs((corpo or b"").decode())
        assert dados["chat_id"] == [CHAT]
        self.mensagens.append(dados["text"][0])
        return self.telegram_status, json.dumps({"ok": False, "description": SEGREDO_NO_CORPO}).encode()


class Relogio:
    def __init__(self, t: datetime = T0) -> None:
        self.t = t

    def __call__(self) -> datetime:
        return self.t


def _rodar(tmp_path: Path, rede: Rede, relogio: Relogio, discos: dict[str, float] | None = None) -> list[str]:
    discos = discos if discos is not None else {"/": 40.0}
    return vigia.rodar(env=ENV, estado_path=tmp_path / "vigia.json", http=rede, relogio=relogio,
                       disco=lambda p: discos[p], discos=list(discos))


def _sem_vazamento(rede: Rede) -> None:
    for m in rede.mensagens:
        assert TOKEN not in m and "TOKEN" not in m
        assert SEGREDO_NO_CORPO not in m


def test_saude_ok_nada_enviado(tmp_path: Path) -> None:
    rede, rel = Rede(), Relogio()
    for _ in range(5):
        assert _rodar(tmp_path, rede, rel) == []
        rel.t += timedelta(minutes=1)
    assert rede.mensagens == []
    assert json.loads((tmp_path / "vigia.json").read_text())["falhas_saude"] == 0


def _cenario(causa: str) -> tuple[Rede, dict[str, float]]:
    s = saude_ok()
    discos = {"/": 40.0}
    rede = Rede(s)
    if causa == "saude":
        rede.cair = True
    elif causa == "saude503":
        rede.status = 503
    elif causa == "disco:/":
        discos["/"] = 91.0
    elif causa == "worker:rapido":
        s["workers"]["rapido"] = _z(T0 - timedelta(minutes=6))
    elif causa == "snapshot:pc":
        s["ultimo_backup"]["pc"] = _z(T0 - timedelta(hours=37))
    elif causa == "snapshot:ayanami":
        s["ultimo_backup"]["ayanami"] = None
    elif causa == "backup_falhou":
        s["backup_falhou"] = True
    elif causa == "restore":
        s["restore_teste"] = {"verde": False, "ts": _z(T0)}
    return rede, discos


CAUSAS = ["saude", "saude503", "disco:/", "worker:rapido", "snapshot:pc", "snapshot:ayanami",
          "backup_falhou", "restore"]


@pytest.mark.parametrize("causa", CAUSAS)
def test_cada_causa_uma_mensagem_e_nao_repete_em_6h(tmp_path: Path, causa: str) -> None:
    rede, discos = _cenario(causa)
    rel = Relogio()
    chave = "saude" if causa.startswith("saude") else causa
    enviadas: list[str] = []
    # 6 h menos 1 min, de minuto em minuto: só 1 mensagem
    for _ in range(6 * 60):
        if not rede.cair and rede.status == 200:
            rede.saude = _envelhecer(rede.saude, rel.t)
        enviadas += _rodar(tmp_path, rede, rel, discos)
        rel.t += timedelta(minutes=1)
    assert enviadas == [chave]
    assert len(rede.mensagens) == 1
    # passadas as 6 h, repete uma vez
    rel.t = T0 + timedelta(hours=6, minutes=2 if causa.startswith("saude") else 0)
    if not rede.cair and rede.status == 200:
        rede.saude = _envelhecer(rede.saude, rel.t)
    assert _rodar(tmp_path, rede, rel, discos) == [chave]
    assert len(rede.mensagens) == 2
    _sem_vazamento(rede)


def _envelhecer(s: dict, agora: datetime) -> dict:
    """Mantém os batimentos/backups saudáveis frescos com o relógio andando (só os quebrados envelhecem)."""
    s = json.loads(json.dumps(s))
    for fila, ts in s["workers"].items():
        if ts and T0 - datetime.fromisoformat(ts.replace("Z", "+00:00")) <= timedelta(minutes=1):
            s["workers"][fila] = _z(agora)
    return s


def test_saude_so_alerta_na_terceira_falha_e_zera_ao_voltar(tmp_path: Path) -> None:
    rede, rel = Rede(), Relogio()
    rede.cair = True
    assert _rodar(tmp_path, rede, rel) == []
    assert _rodar(tmp_path, rede, rel) == []
    rede.cair = False  # voltou: zera
    assert _rodar(tmp_path, rede, rel) == []
    rede.cair = True
    assert _rodar(tmp_path, rede, rel) == []
    assert _rodar(tmp_path, rede, rel) == []
    assert _rodar(tmp_path, rede, rel) == ["saude"]
    assert rede.mensagens == ["⚠ Ayanami: /saude falhando (3x seguidas)"]


def test_causas_independentes_e_telegram_recusado_tenta_de_novo(tmp_path: Path) -> None:
    s = saude_ok()
    s["backup_falhou"] = True
    rede, rel = Rede(s, telegram_status=500), Relogio()
    discos = {"/": 90.0, "/opt/ayanami/dados": 86.5}
    assert _rodar(tmp_path, rede, rel, discos) == []  # Telegram recusou: nada marcado
    assert len(rede.mensagens) == 3
    rede.telegram_status = 200
    rel.t += timedelta(minutes=1)
    esperado = ["backup_falhou", "disco:/", "disco:/opt/ayanami/dados"]
    assert sorted(_rodar(tmp_path, rede, rel, discos)) == esperado
    rel.t += timedelta(minutes=1)
    assert _rodar(tmp_path, rede, rel, discos) == []
    _sem_vazamento(rede)


def test_mensagem_nao_ecoa_campos_estranhos_da_saude(tmp_path: Path) -> None:
    s = saude_ok()
    s["workers"] = {f"x {SEGREDO_NO_CORPO} {TOKEN}": None}
    rede = Rede(s)
    assert _rodar(tmp_path, rede, Relogio()) == ["worker:?"]
    _sem_vazamento(rede)


def test_sem_token_nao_envia_nem_marca(tmp_path: Path) -> None:
    rede = Rede()
    rede.cair = True
    for _ in range(3):
        assert vigia.rodar(env={}, estado_path=tmp_path / "v.json", http=rede, relogio=Relogio(),
                           disco=lambda p: 10.0, discos=["/"]) == []
    assert rede.mensagens == []
    assert json.loads((tmp_path / "v.json").read_text())["enviados"] == {}


def test_ler_env(tmp_path: Path) -> None:
    p = tmp_path / ".env"
    p.write_text('# c\nTELEGRAM_BOT_TOKEN="000:falso"\nexport TELEGRAM_CHAT_ID=7\nLIXO\n', encoding="utf-8")
    assert vigia.ler_env(p) == {"TELEGRAM_BOT_TOKEN": "000:falso", "TELEGRAM_CHAT_ID": "7"}
    assert vigia.ler_env(tmp_path / "nao-existe") == {}


def test_estado_corrompido_recomeca(tmp_path: Path) -> None:
    (tmp_path / "vigia.json").write_text("{lixo", encoding="utf-8")
    assert _rodar(tmp_path, Rede(), Relogio()) == []


def test_http_urllib_com_servidor_local(tmp_path: Path) -> None:
    """Caminho real do ``urllib`` contra servidor falso em 127.0.0.1 (saúde 503 ×3 + Telegram)."""
    recebidos: list[tuple[str, bytes]] = []

    class H(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(503)
            self.end_headers()
            self.wfile.write(SEGREDO_NO_CORPO.encode())

        def do_POST(self) -> None:  # noqa: N802
            n = int(self.headers.get("Content-Length") or 0)
            recebidos.append((self.path, self.rfile.read(n)))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, *a: object) -> None:
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        for _ in range(3):
            out = vigia.rodar(env=ENV, estado_path=tmp_path / "v.json", relogio=Relogio(),
                              disco=lambda p: 1.0, discos=["/"], url_saude=f"{base}/saude",
                              telegram_base=base)
    finally:
        srv.shutdown()
        srv.server_close()
    assert out == ["saude"]
    assert len(recebidos) == 1
    caminho, corpo = recebidos[0]
    assert caminho == f"/bot{TOKEN}/sendMessage"
    texto = urllib.parse.parse_qs(corpo.decode())["text"][0]
    assert TOKEN not in texto and SEGREDO_NO_CORPO not in texto


def test_main_sai_1_sem_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vigia, "http_urllib", Rede())
    monkeypatch.setattr(vigia.rodar, "__kwdefaults__",
                        {**vigia.rodar.__kwdefaults__, "http": Rede(), "disco": lambda p: 1.0})
    assert vigia.main(["--env", str(tmp_path / "nada"), "--estado", str(tmp_path / "v.json"),
                       "--disco", "/", "--sem-servidor"]) == 1


# ---- servidor e Minecraft (Y1.3b): /proc em tmp, docker injetado, RCON falso local ----

KIB_GIB = 1024 * 1024


class Proc:
    """``/proc`` falso: ``stat`` acumulado por núcleo, ``meminfo`` e ``loadavg``."""

    def __init__(self, raiz: Path) -> None:
        self.raiz = raiz
        raiz.mkdir(exist_ok=True)
        self.cont = {n: [0, 0] for n in range(8)}  # ocupado, ocioso (jiffies)
        self.mem(disp_gib=4.0, swap_usado_gib=0.5)
        (raiz / "loadavg").write_text("5.50 4.20 3.10 7/900 12345\n")
        self.passo(mc=50, ay=20)

    def passo(self, mc: float, ay: float) -> None:
        for n in range(8):
            uso = mc if n < 6 else ay
            self.cont[n][0] += int(uso)
            self.cont[n][1] += 100 - int(uso)
        linhas = ["cpu  1 2 3 4 5 6 7 8 0 0"]
        for n, (oc, oci) in self.cont.items():
            # user nice system idle iowait irq softirq steal guest guest_nice
            linhas.append(f"cpu{n} {oc} 0 0 {oci} 0 0 0 0 {oc} 0")
        (self.raiz / "stat").write_text("\n".join(linhas) + "\nintr 1 2 3\n")

    def mem(self, disp_gib: float, swap_usado_gib: float) -> None:
        (self.raiz / "meminfo").write_text(
            f"MemTotal:       {int(15.6 * KIB_GIB)} kB\nMemFree:  100 kB\n"
            f"MemAvailable:   {int(disp_gib * KIB_GIB)} kB\nSwapTotal:      {8 * KIB_GIB} kB\n"
            f"SwapFree:       {int((8 - swap_usado_gib) * KIB_GIB)} kB\n")


class DockerFalso:
    def __init__(self) -> None:
        self.status = "running"
        self.restarts = 0
        self.ausente = False
        self.chamadas: list[list[str]] = []

    def __call__(self, argv: list[str]) -> tuple[int, str, str]:
        self.chamadas.append(argv)
        if self.ausente:
            return 1, "[]", "Error: No such container: minecraft"
        info = [{"State": {"Status": self.status, "StartedAt": "2026-10-12T11:00:00.123Z"},
                 "RestartCount": self.restarts}]
        return 0, json.dumps(info), ""


SENHA_RCON = "senha-rcon-falsa"


class RconFalso:
    """Servidor RCON em 127.0.0.1:0 (protocolo real, por ``socketserver``)."""

    def __init__(self) -> None:
        import socketserver
        import struct

        self.tps = "20.0"
        self.spark = True
        self.comandos: list[str] = []
        dono = self

        class H(socketserver.BaseRequestHandler):
            def handle(self) -> None:
                def ler():
                    cab = self.request.recv(4)
                    if len(cab) < 4:
                        return None
                    (tam,) = struct.unpack("<i", cab)
                    dados = b""
                    while len(dados) < tam:
                        dados += self.request.recv(tam - len(dados))
                    rid, tipo = struct.unpack("<ii", dados[:8])
                    return rid, tipo, dados[8:-2].decode()

                def enviar(rid: int, tipo: int, corpo: str) -> None:
                    d = struct.pack("<ii", rid, tipo) + corpo.encode() + b"\x00\x00"
                    self.request.sendall(struct.pack("<i", len(d)) + d)

                rid, tipo, corpo = ler()
                assert tipo == 3
                if corpo != SENHA_RCON:
                    enviar(-1, 2, "")
                    return
                enviar(rid, 2, "")
                while (p := ler()) is not None:
                    rid, _, cmd = p
                    dono.comandos.append(cmd)
                    if cmd == "list":
                        enviar(rid, 0, "There are 2 of a max of 20 players online: Pedro, Rei")
                    elif dono.spark:
                        enviar(rid, 0, f"§8[§e⚡§8] §7TPS from last 5s, 10s, 1m, 5m, 15m:\n§8[§e⚡§8] "
                                       f"§a*20.0, §a19.9, §c{dono.tps}, §a20.0, §a20.0\n\nTick durations")
                    else:
                        enviar(rid, 0, "§cUnknown or incomplete command, see below for error")

        self.srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        self.porta = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def fechar(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()


@pytest.fixture
def rcon():
    r = RconFalso()
    yield r
    r.fechar()


@pytest.fixture
def srv(tmp_path: Path, rcon: RconFalso):
    proc = Proc(tmp_path / "proc")
    docker = DockerFalso()
    (tmp_path / "mc.env").write_text(f"RCON_PASSWORD={SENHA_RCON}\n")
    conf = vigia.ConfServidor.do_env(
        {"VIGIA_RCON_PORTA": str(rcon.porta), "VIGIA_MC_ENV": str(tmp_path / "mc.env"),
         "VIGIA_RESUMO": str(tmp_path / "dados" / "servidor.json")},
        proc=proc.raiz, docker=docker)
    return proc, docker, conf


def _passar(tmp_path: Path, conf, rel: Relogio, rede: Rede | None = None) -> list[str]:
    rede = rede or Rede()
    rede.saude = saude_ok(rel.t)  # /saude sempre em dia: só o servidor alerta aqui
    out = vigia.rodar(env=ENV, estado_path=tmp_path / "vigia.json", http=rede, relogio=rel,
                      disco=lambda p: 10.0, discos=["/"], servidor=conf)
    rel.t += timedelta(minutes=1)
    return out


def _resumo(conf) -> dict:
    return json.loads(conf.resumo.read_text())


def test_servidor_ok_resumo_completo_sem_alerta(tmp_path: Path, srv, rcon) -> None:
    proc, docker, conf = srv
    rel, rede = Relogio(), Rede()
    for _ in range(3):
        proc.passo(mc=60, ay=25)
        assert _passar(tmp_path, conf, rel, rede) == []
    assert rede.mensagens == []
    r = _resumo(conf)
    assert r["cpu"]["minecraft"] == {"nucleos": "0-5", "uso": 60.0}
    assert r["cpu"]["ayanami"] == {"nucleos": "6-7", "uso": 25.0}
    assert r["load"] == [5.5, 4.2, 3.1]
    assert r["ram"]["disponivel_gib"] == 4.0 and r["swap"]["usado_gib"] == 0.5
    mc = r["minecraft"]
    assert mc["status"] == "running" and mc["restart_count"] == 0
    assert mc["jogadores"] == 2 and mc["max_jogadores"] == 20 and mc["nomes"] == ["Pedro", "Rei"]
    assert mc["spark"] is True and mc["tps"] == 20.0 and mc["rcon"] == "ok"
    assert r["alertas"] == []
    assert not conf.resumo.with_name("servidor.json.tmp").exists()
    assert SENHA_RCON not in conf.resumo.read_text()
    assert docker.chamadas[0] == ["docker", "inspect", "--type", "container", "minecraft"]


def test_cpu_minecraft_alerta_na_quinta_leitura_alta(tmp_path: Path, srv) -> None:
    proc, _, conf = srv
    rel, rede = Relogio(), Rede()
    for _ in range(4):
        proc.passo(mc=97, ay=10)
        assert _passar(tmp_path, conf, rel, rede) == []
    proc.passo(mc=50, ay=10)  # uma leitura normal zera a contagem
    assert _passar(tmp_path, conf, rel, rede) == []
    for _ in range(4):
        proc.passo(mc=97, ay=10)
        assert _passar(tmp_path, conf, rel, rede) == []
    proc.passo(mc=97, ay=10)
    assert _passar(tmp_path, conf, rel, rede) == ["cpu:minecraft"]
    proc.passo(mc=99, ay=10)
    assert _passar(tmp_path, conf, rel, rede) == []  # 6 h de silêncio
    assert len(rede.mensagens) == 1 and "0-5" in rede.mensagens[0]
    _sem_vazamento(rede)


def test_ayanami_alta_nao_alerta(tmp_path: Path, srv) -> None:
    proc, _, conf = srv
    rel = Relogio()
    for _ in range(7):
        proc.passo(mc=10, ay=100)
        assert _passar(tmp_path, conf, rel) == []


@pytest.mark.parametrize(("disp", "swap", "esperado"), [(0.8, 0.5, ["ram"]), (4.0, 6.5, ["swap"]),
                                                        (1.2, 5.9, [])])
def test_ram_e_swap(tmp_path: Path, srv, disp: float, swap: float, esperado: list[str]) -> None:
    proc, _, conf = srv
    proc.mem(disp_gib=disp, swap_usado_gib=swap)
    assert _passar(tmp_path, conf, Relogio()) == esperado
    assert _resumo(conf)["alertas"] == esperado


def test_container_parado_e_reinicio(tmp_path: Path, srv, rcon) -> None:
    _, docker, conf = srv
    rel = Relogio()
    docker.restarts = 3
    assert _passar(tmp_path, conf, rel) == []  # 1ª leitura só guarda o RestartCount
    docker.restarts = 4
    assert _passar(tmp_path, conf, rel) == ["minecraft:reiniciou"]
    assert _passar(tmp_path, conf, rel) == []
    docker.status = "exited"
    n = len(rcon.comandos)
    assert _passar(tmp_path, conf, rel) == ["minecraft:parado"]
    assert len(rcon.comandos) == n  # parado: nem tenta o RCON
    assert _resumo(conf)["minecraft"]["status"] == "exited"


def test_minecraft_ausente_nao_e_erro(tmp_path: Path, srv, rcon) -> None:
    _, docker, conf = srv
    docker.ausente = True
    assert _passar(tmp_path, conf, Relogio()) == []
    assert _resumo(conf)["minecraft"] == "ausente"
    assert rcon.comandos == []


def test_docker_inexistente_no_host(tmp_path: Path, srv) -> None:
    _, _, conf = srv

    def sem_docker(argv: list[str]) -> tuple[int, str, str]:
        raise FileNotFoundError("docker")

    conf.docker = sem_docker
    assert _passar(tmp_path, conf, Relogio()) == []
    assert _resumo(conf)["minecraft"] == {"status": "erro"}


def test_tps_baixo_alerta_na_terceira_leitura(tmp_path: Path, srv, rcon) -> None:
    _, _, conf = srv
    rel, rede = Relogio(), Rede()
    rcon.tps = "12.5"
    assert _passar(tmp_path, conf, rel, rede) == []
    assert _passar(tmp_path, conf, rel, rede) == []
    assert _passar(tmp_path, conf, rel, rede) == ["minecraft:tps"]
    assert "12.5" in rede.mensagens[0]
    assert _resumo(conf)["minecraft"]["tps"] == 12.5
    _sem_vazamento(rede)


def test_sem_spark_so_list(tmp_path: Path, srv, rcon) -> None:
    _, _, conf = srv
    rcon.spark = False
    rel = Relogio()
    for _ in range(4):
        assert _passar(tmp_path, conf, rel) == []
    mc = _resumo(conf)["minecraft"]
    assert mc["spark"] is False and mc["tps"] is None and mc["jogadores"] == 2


def test_rcon_senha_errada_ou_fora(tmp_path: Path, srv, rcon) -> None:
    _, _, conf = srv
    (conf.mc_env).write_text("RCON_PASSWORD=outra\n")
    assert _passar(tmp_path, conf, Relogio()) == []
    assert _resumo(conf)["minecraft"]["rcon"] == "erro (PermissionError)"
    conf.mc_env.write_text("# sem senha\n")
    assert _passar(tmp_path, conf, Relogio()) == []
    assert _resumo(conf)["minecraft"]["rcon"] == "sem_senha"
    rcon.fechar()
    conf.mc_env.write_text(f"RCON_PASSWORD={SENHA_RCON}\n")
    _passar(tmp_path, conf, Relogio())
    assert _resumo(conf)["minecraft"]["rcon"].startswith("erro")


def test_config_pelo_env(tmp_path: Path) -> None:
    c = vigia.ConfServidor.do_env({"VIGIA_MC_CONTAINER": "mc2", "VIGIA_CPU_LIMITE": "90",
                                   "VIGIA_TPS_LEITURAS": "x", "VIGIA_NUCLEOS_MC": "0-3,8"})
    assert c.container == "mc2" and c.cpu_limite == 90.0 and c.tps_leituras == 3
    assert vigia._nucleos(c.nucleos_mc) == [0, 1, 2, 3, 8]
    assert c.rcon_porta == 25575 and c.resumo == Path("/opt/ayanami/dados/servidor.json")


def test_main_com_servidor_falso(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, srv) -> None:
    _, _, conf = srv
    monkeypatch.setattr(vigia.ConfServidor, "do_env", classmethod(lambda cls, env: conf))
    monkeypatch.setattr(vigia.rodar, "__kwdefaults__",
                        {**vigia.rodar.__kwdefaults__, "http": Rede(), "disco": lambda p: 1.0,
                         "relogio": Relogio()})
    (tmp_path / ".env").write_text(f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_CHAT_ID={CHAT}\n")
    assert vigia.main(["--env", str(tmp_path / ".env"), "--estado", str(tmp_path / "v.json"),
                       "--disco", "/"]) == 0
    assert _resumo(conf)["minecraft"]["status"] == "running"


# ---- units (estático; nada é instalado) ----

def _unit(nome: str) -> configparser.ConfigParser:
    cp = configparser.ConfigParser(strict=False, interpolation=None)
    cp.optionxform = str
    cp.read(VIGIA / nome, encoding="utf-8")
    return cp


def test_timer_1_min() -> None:
    t = _unit("ayanami-vigia.timer")
    assert t["Timer"]["OnUnitActiveSec"] == "1min"
    assert t["Timer"]["OnBootSec"] == "1min"
    assert t["Timer"]["Unit"] == "ayanami-vigia.service"
    assert t["Install"]["WantedBy"] == "timers.target"


def test_servico_oneshot_no_python3_do_host() -> None:
    s = _unit("ayanami-vigia.service")["Service"]
    assert s["Type"] == "oneshot"
    assert s["ExecStart"].startswith("/usr/bin/python3 /opt/ayanami/deploy/ayanami/vigia/vigia.py")
    assert "--estado /opt/ayanami/dados/vigia.json" in s["ExecStart"]
    assert s["ReadWritePaths"] == "/opt/ayanami/dados"
    assert "docker" not in s["ExecStart"]


def test_so_biblioteca_padrao_e_sem_segredo() -> None:
    import ast

    fonte = (VIGIA / "vigia.py").read_text(encoding="utf-8")
    mods = set()
    for no in ast.walk(ast.parse(fonte)):
        if isinstance(no, ast.Import):
            mods |= {a.name.split(".")[0] for a in no.names}
        elif isinstance(no, ast.ImportFrom) and no.module:
            mods.add(no.module.split(".")[0])
    mods.discard("__future__")
    assert mods <= set(sys.stdlib_module_names), mods - set(sys.stdlib_module_names)
    for nome in ("vigia.py", "ayanami-vigia.service", "ayanami-vigia.timer"):
        texto = (VIGIA / nome).read_text(encoding="utf-8")
        for proibido in ("compose down", "volume rm", "DROP ", "TRUNCATE", "--clean"):
            assert proibido not in texto
