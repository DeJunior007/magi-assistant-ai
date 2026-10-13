"""C1.4 — driver Android TV com ``AndroidTVRemote`` falso (sem rede, sem TV real). CA-Y44."""

from __future__ import annotations

import asyncio
import stat

import pytest
from androidtvremote2.exceptions import CannotConnect, ConnectionClosed, InvalidAuth

from magi.casa.apps import AppAndroidTv, AppCatalogo, AppEntrada
from magi.casa.driver import ContextoDriver, Key, Motivo, TvConfig, TvDriver
from magi.casa.drivers import androidtv
from magi.casa.drivers.androidtv import DriverAndroidTv, caminhos_cert, parear
from magi.casa.falso import RelogioFalso

APPS = AppCatalogo(
    [
        AppEntrada(
            id="netflix",
            nome="Netflix",
            androidtv=AppAndroidTv(link="https://www.netflix.com/title", pacote="com.netflix.ninja"),
        ),
        AppEntrada(id="so_roku", nome="Só Roku", roku="99"),
    ]
)


class RemotoFalso:
    """Imita a API pública do ``AndroidTVRemote`` 0.3.2 usada pelo driver."""

    def __init__(self, certfile: str = "", keyfile: str = "", host: str = "") -> None:
        self.certfile, self.keyfile, self.host = certfile, keyfile, host
        self.is_on: bool | None = True
        self.current_app: str | None = "com.google.android.tvlauncher"
        self.volume_info: dict | None = {"level": 10, "max": 50, "muted": False}
        self.enviados: list[tuple[str, object]] = []
        self.cbs: dict[str, list] = {"on": [], "app": [], "vol": [], "disp": []}
        self.conectar_erro: Exception | None = None
        self.conexoes = 0
        self.reconectando = 0
        self.desconectado = False
        self.auth_cb = None
        self.ao_enviar = None  # chamável (remoto, tipo, valor) para reagir a um comando
        self.codigos_certos = {"A1B2C3"}
        self.pareamentos = 0

    def add_is_on_updated_callback(self, cb):
        self.cbs["on"].append(cb)

    def add_current_app_updated_callback(self, cb):
        self.cbs["app"].append(cb)

    def add_volume_info_updated_callback(self, cb):
        self.cbs["vol"].append(cb)

    def add_is_available_updated_callback(self, cb):
        self.cbs["disp"].append(cb)

    def remove_is_on_updated_callback(self, cb):
        self.cbs["on"].remove(cb)

    def remove_current_app_updated_callback(self, cb):
        self.cbs["app"].remove(cb)

    def remove_volume_info_updated_callback(self, cb):
        self.cbs["vol"].remove(cb)

    def remove_is_available_updated_callback(self, cb):
        self.cbs["disp"].remove(cb)

    async def async_connect(self):
        self.conexoes += 1
        if self.conectar_erro is not None:
            raise self.conectar_erro

    def keep_reconnecting(self, invalid_auth_callback=None):
        self.reconectando += 1
        self.auth_cb = invalid_auth_callback

    def disconnect(self):
        self.desconectado = True

    # empurra da "TV"
    def emitir(self, qual: str, valor) -> None:
        if qual == "on":
            self.is_on = valor
        elif qual == "app":
            self.current_app = valor
        elif qual == "vol":
            self.volume_info = valor
        for cb in list(self.cbs[qual]):
            cb(valor)

    def _registrar(self, tipo, valor):
        if self.desconectado:
            raise ConnectionClosed("Called after disconnect")
        self.enviados.append((tipo, valor))
        if self.ao_enviar is not None:
            self.ao_enviar(self, tipo, valor)

    def send_key_command(self, key_code, direction="SHORT"):
        self._registrar("key", key_code)

    def send_text(self, text):
        self._registrar("text", text)

    def send_launch_app_command(self, link):
        self._registrar("app", link)

    async def async_start_pairing(self):
        self.pareamentos += 1

    async def async_finish_pairing(self, code):
        if code not in self.codigos_certos:
            raise InvalidAuth("bad code")


def _tv(**kw) -> TvConfig:
    return TvConfig(id=kw.pop("id", "sala"), nome="TV da sala", driver="androidtv", ip="10.0.0.9", **kw)


@pytest.fixture
def pareada(tmp_path):
    d = tmp_path / "pareamentos"
    d.mkdir(mode=0o700)
    for tv_id in ("sala", "quarto"):
        for p in caminhos_cert(tv_id, d):
            p.write_text("PEM falso")
            p.chmod(0o600)
    return d


def _driver(pareada, relogio, remoto=None, tv=None, dormir=None):
    remoto = remoto or RemotoFalso()
    criados: list[RemotoFalso] = []

    def fabrica(crt, key, host):
        remoto.certfile, remoto.keyfile, remoto.host = crt, key, host
        criados.append(remoto)
        return remoto

    ctx = ContextoDriver(apps=APPS, dir_pareamento=pareada, relogio=relogio)
    d = DriverAndroidTv(tv or _tv(), ctx, fabrica=fabrica, dormir=dormir or relogio.dormir)
    return d, remoto, criados


async def test_contrato_e_fabrica(pareada):
    d = androidtv.criar(_tv(), ContextoDriver(apps=APPS, dir_pareamento=pareada))
    assert isinstance(d, TvDriver)
    assert d.nome == "androidtv"
    assert d.capacidades.apps == ("netflix",)
    assert d.capacidades.pode(androidtv.Cap.VOL_SET)  # emulada
    assert androidtv.Cap.VOL_SET not in d.capacidades.caps


async def test_ca_y44_volume_power_app_entrada(pareada, relogio):
    d, r, _ = _driver(pareada, relogio)
    res = await d.conectar()
    assert res.ok and r.reconectando == 1
    assert r.certfile.endswith("sala.atv.crt") and r.host == "10.0.0.9"
    # volume_info level=10,max=50 → 20
    assert (await d.state()).volume == 20
    assert d.capacidades.vol_max == 50
    # power(True) com is_on=True → nenhuma tecla
    assert (await d.power(True)).ok
    assert r.enviados == []
    # deep link do catálogo
    assert (await d.app("netflix")).ok
    assert r.enviados == [("app", "https://www.netflix.com/title")]
    # entrada sem mudança de current_app → NAO_SUPORTADO
    res = await d.input("hdmi2")
    assert res.motivo == Motivo.NAO_SUPORTADO
    assert r.enviados[-1] == ("key", 244)


async def test_callbacks_atualizam_estado(pareada, relogio):
    d, r, _ = _driver(pareada, relogio)
    await d.conectar()
    r.emitir("app", "com.netflix.ninja")
    r.emitir("vol", {"level": 37, "max": 100, "muted": True})
    r.emitir("on", False)
    e = await d.state()
    assert (e.app, e.volume, e.mudo, e.ligada, e.online) == ("netflix", 37, True, False, True)
    r.emitir("app", "org.desconhecido")
    assert (await d.state()).app == "org.desconhecido"


async def test_power_alterna_so_quando_contradiz(pareada, relogio):
    d, r, _ = _driver(pareada, relogio)
    await d.conectar()
    r.ao_enviar = lambda rr, t, v: rr.emitir("on", False) if v == "POWER" else None
    res = await d.power(False)
    assert res.ok and res.estado.ligada is False
    assert r.enviados == [("key", "POWER")]
    # ligar sem a TV acordar → STANDBY_PROFUNDO depois de ~8 s (relógio falso)
    r.ao_enviar = None
    t0 = relogio()
    res = await d.power(True)
    assert res.motivo == Motivo.STANDBY_PROFUNDO
    assert relogio() - t0 >= androidtv.ESPERA_POWER_S


async def test_power_estado_desconhecido_nao_envia(pareada, relogio):
    r = RemotoFalso()
    r.is_on = None
    d, r, _ = _driver(pareada, relogio, r)
    await d.conectar()
    res = await d.power(True)
    assert res.motivo == Motivo.NAO_SUPORTADO and "desconhecido" in res.detalhe
    assert r.enviados == []


async def test_entrada_com_troca_de_app_confirma(pareada, relogio):
    d, r, _ = _driver(pareada, relogio)
    await d.conectar()
    r.ao_enviar = lambda rr, t, v: rr.emitir("app", "com.tcl.tv.hdmi1") if v == 243 else None
    res = await d.input("hdmi1")
    assert res.ok and res.estado.entrada == "hdmi1"
    assert (await d.input("xpto")).motivo == Motivo.ENTRADA_DESCONHECIDA
    assert (await d.input("tv")).motivo == Motivo.NAO_SUPORTADO


async def test_adb_so_gancho(pareada, relogio):
    d, r, _ = _driver(pareada, relogio, tv=_tv(adb=True))
    await d.conectar()
    res = await d.input("hdmi3")
    assert res.motivo == Motivo.NAO_SUPORTADO and "ADB" in res.detalhe


async def test_volume_mudo_canal_teclas_texto(pareada, relogio, log_casa):
    d, r, _ = _driver(pareada, relogio)
    await d.conectar()
    assert (await d.volume(step=3)).ok
    assert (await d.volume(step=-99)).ok
    assert [v for _, v in r.enviados].count("VOLUME_UP") == 3
    assert [v for _, v in r.enviados].count("VOLUME_DOWN") == 30
    assert (await d.volume(set_to=40)).motivo == Motivo.NAO_SUPORTADO
    r.enviados.clear()
    assert (await d.mute(False)).ok  # já sem mudo → nada
    assert r.enviados == []
    assert (await d.mute(True)).ok
    assert (await d.mute(None)).ok
    assert r.enviados == [("key", "VOLUME_MUTE")] * 2
    r.enviados.clear()
    assert (await d.channel(-2)).ok
    assert (await d.key(Key.OK)).ok
    assert (await d.key(Key.PLAY_PAUSE)).ok
    assert r.enviados == [
        ("key", "CHANNEL_DOWN"),
        ("key", "CHANNEL_DOWN"),
        ("key", "DPAD_CENTER"),
        ("key", "MEDIA_PLAY_PAUSE"),
    ]
    assert (await d.text("senha secreta")).ok
    assert r.enviados[-1] == ("text", "senha secreta")
    assert "senha secreta" not in log_casa.texto
    assert (await d.app("so_roku")).motivo == Motivo.APP_DESCONHECIDO
    assert (await d.app("nada")).motivo == Motivo.APP_DESCONHECIDO


async def test_sem_pareamento_e_falhas_de_conexao(tmp_path, pareada, relogio):
    d, r, _ = _driver(tmp_path / "vazio", relogio)
    assert (await d.conectar()).motivo == Motivo.NAO_PAREADO
    assert (await d.key(Key.HOME)).motivo == Motivo.NAO_PAREADO
    assert r.conexoes == 0

    for erro, motivo in (
        (CannotConnect("x"), Motivo.OFFLINE),
        (ConnectionClosed("x"), Motivo.OFFLINE),
        (InvalidAuth("x"), Motivo.NAO_PAREADO),
        (RuntimeError("x"), Motivo.ERRO_DRIVER),
    ):
        r = RemotoFalso()
        r.conectar_erro = erro
        d, r, _ = _driver(pareada, relogio, r)
        res = await d.conectar()
        assert res.motivo == motivo and not res.ok
        assert r.desconectado
        assert (await d.state()).online is False


async def test_auth_invalida_na_reconexao(pareada, relogio):
    d, r, _ = _driver(pareada, relogio)
    await d.conectar()
    r.auth_cb()
    assert (await d.key(Key.HOME)).motivo == Motivo.NAO_PAREADO


async def test_comando_espera_reconexao_ate_1_5s(pareada, relogio):
    d, r, _ = _driver(pareada, relogio)
    await d.conectar()
    r.emitir("disp", False)
    t0 = relogio()
    res = await d.key(Key.HOME)
    assert res.motivo == Motivo.OFFLINE and res.detalhe == "reconectando"
    assert androidtv.ESPERA_RECONEXAO_S <= relogio() - t0 < androidtv.ESPERA_RECONEXAO_S + 0.2
    assert r.enviados == []


async def test_reconexao_cai_3x_sem_bloquear_outra_tv(pareada):
    relogio = RelogioFalso(0.0)
    voltas: list[RemotoFalso] = []

    async def dormir(s: float) -> None:  # cede o loop (como o sleep real) sem esperar de verdade
        relogio.avancar(s)
        await asyncio.sleep(0)
        for rr in voltas:
            rr.ticks = getattr(rr, "ticks", 0) + 1
            if rr.ticks >= 5:  # a "lib" reconecta depois de 5 passos (0,25 s)
                voltas.remove(rr)
                rr.emitir("disp", True)

    a, ra, _ = _driver(pareada, relogio, dormir=dormir)
    b, rb, _ = _driver(pareada, relogio, RemotoFalso(), tv=_tv(id="quarto"), dormir=dormir)
    assert (await a.conectar()).ok and (await b.conectar()).ok

    for _ in range(3):
        ra.ticks = 0
        ra.emitir("disp", False)
        voltas.append(ra)
        tarefa_a = asyncio.create_task(a.key(Key.HOME))
        await asyncio.sleep(0)
        res_b = await b.key(Key.BACK)  # a TV do quarto não espera a da sala
        assert res_b.ok and not tarefa_a.done()
        assert (await tarefa_a).ok
    assert ra.enviados == [("key", "HOME")] * 3
    assert rb.enviados == [("key", "BACK")] * 3
    assert ra.reconectando == 1 and ra.conexoes == 1  # reconexão é da lib, não reabre


async def test_conexao_fechada_no_envio_vira_offline_e_reabre(pareada, relogio):
    d, r, criados = _driver(pareada, relogio)
    await d.conectar()
    r.desconectado = True
    assert (await d.key(Key.UP)).motivo == Motivo.OFFLINE
    await d.fechar()
    r.desconectado = False
    assert (await d.key(Key.UP)).ok
    assert len(criados) == 2 and r.conexoes == 2


# ── pareamento por código (§12.3, CA-Y48 parte Android TV) ─────────────────────


def _gerar_falso(nome: str) -> tuple[bytes, bytes]:
    return b"-----BEGIN CERTIFICATE-----\nfalso\n", b"-----BEGIN PRIVATE KEY-----\nfalso\n"


def _modo(p) -> int:
    return stat.S_IMODE(p.stat().st_mode)


async def test_parear_codigo_certo_grava_0600(tmp_path, log_casa):
    d = tmp_path / "pareamentos"
    r = RemotoFalso()
    codigos = iter(["zzzzzz", " A1B2C3 "])

    async def pedir() -> str:
        return next(codigos)

    ctx = ContextoDriver(dir_pareamento=d)
    res = await parear(_tv(), ctx, pedir, fabrica=lambda c, k, h: r, gerar_cert=_gerar_falso)
    assert res.ok and r.pareamentos == 2 and r.desconectado
    crt, key = caminhos_cert("sala", d)
    assert _modo(crt) == 0o600 and _modo(key) == 0o600 and _modo(d) == 0o700
    assert sorted(p.name for p in d.iterdir()) == ["sala.atv.crt", "sala.atv.key"]
    assert "A1B2C3" not in log_casa.texto and "zzzzzz" not in log_casa.texto


async def test_parear_3_errados_aborta_sem_gravar(tmp_path):
    d = tmp_path / "pareamentos"
    r = RemotoFalso()

    async def pedir() -> str:
        return "000000"

    ctx = ContextoDriver(dir_pareamento=d)
    res = await parear(_tv(), ctx, pedir, fabrica=lambda c, k, h: r, gerar_cert=_gerar_falso)
    assert not res.ok and res.motivo == Motivo.ACESSO_NEGADO and r.pareamentos == 3
    assert list(d.iterdir()) == []


async def test_parear_prazo_e_cancelamento(tmp_path):
    d = tmp_path / "pareamentos"
    ctx = ContextoDriver(dir_pareamento=d)

    async def nunca() -> str:
        await asyncio.Event().wait()
        return ""

    r = RemotoFalso()
    res = await parear(_tv(), ctx, nunca, fabrica=lambda c, k, h: r, gerar_cert=_gerar_falso, prazo_s=0.01)
    assert res.motivo == Motivo.TEMPO_ESGOTADO and list(d.iterdir()) == []

    class Cancela(RemotoFalso):
        async def async_finish_pairing(self, code):
            raise ConnectionClosed("cancel")

    async def pedir() -> str:
        return "A1B2C3"

    res = await parear(_tv(), ctx, pedir, fabrica=lambda c, k, h: Cancela(), gerar_cert=_gerar_falso)
    assert res.motivo == Motivo.ACESSO_NEGADO and list(d.iterdir()) == []


async def test_parear_cert_real_da_lib_em_tmp(tmp_path):
    d = tmp_path / "pareamentos"
    vistos: list[tuple[str, str]] = []

    def fabrica(c, k, h):
        vistos.append((c, k))
        return RemotoFalso()

    async def pedir() -> str:
        return "A1B2C3"

    res = await parear(_tv(), ContextoDriver(dir_pareamento=d), pedir, fabrica=fabrica)
    assert res.ok
    crt, key = caminhos_cert("sala", d)
    assert crt.read_text().startswith("-----BEGIN CERTIFICATE-----")
    assert "PRIVATE KEY" in key.read_text()
    assert _modo(crt) == 0o600 and _modo(key) == 0o600
    assert vistos[0][0].endswith(".novo")  # pareia com os provisórios
