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
                       "--disco", "/"]) == 1


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
