import asyncio
import io
import re
from pathlib import Path

import keyring
import keyring.core
import pytest
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

from magi.cli import keys as keys_cli
from magi.common import secrets
from magi.common.config import (
    DEFAULT_DSN,
    TASK_NAMES,
    ConfigError,
    ConfigWatcher,
    config_path,
    load_config,
    parse_config,
)

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "config.example.toml"


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        if self.store.pop((service, username), None) is None:
            raise PasswordDeleteError(username)


@pytest.fixture(autouse=True)
def fake_keyring(monkeypatch):
    """Nunca toca o chaveiro real do usuário (nem inicializa o backend dele)."""
    kr = MemoryKeyring()
    monkeypatch.setattr(keyring.core, "_keyring_backend", kr)
    return kr


# --- config -----------------------------------------------------------------


def test_loads_example():
    cfg = load_config(EXAMPLE)
    assert set(cfg.providers) == {"openai", "gemini"}
    assert cfg.providers["openai"].keys == ("openai-1", "openai-2")
    assert cfg.providers["gemini"].free_tier is True
    assert cfg.providers["openai"].free_tier is False
    # reserva opcional da pesquisa (3.8) e tarefas do Learning Mode (LM0.1)
    assert set(cfg.tasks) == {*TASK_NAMES, "search_fallback", "learning_actions", "learning_observe"}
    assert cfg.task("tts").options["voice"]
    assert cfg.provider_for("search").name == "gemini"
    assert cfg.budget.monthly_usd == 5.0
    assert cfg.database.dsn == DEFAULT_DSN
    assert not str(cfg.paths.data_dir).startswith("~")
    assert cfg.key_names() == ["openai-1", "openai-2", "gemini-1", "gemini-2"]


def test_example_has_no_secrets():
    text = EXAMPLE.read_text()
    assert not re.search(r"sk-[A-Za-z0-9]|AIza[0-9A-Za-z_-]{10}", text)
    assert "api_key" not in text


def test_config_path_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MAGI_CONFIG", str(tmp_path / "x.toml"))
    assert config_path() == tmp_path / "x.toml"
    monkeypatch.delenv("MAGI_CONFIG")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config_path() == tmp_path / "magi" / "config.toml"


def test_load_uses_env(monkeypatch, tmp_path):
    p = tmp_path / "c.toml"
    p.write_bytes(EXAMPLE.read_bytes())
    monkeypatch.setenv("MAGI_CONFIG", str(p))
    assert load_config().source == p


def test_defaults_for_missing_sections():
    cfg = parse_config({})
    assert cfg.providers == {} and cfg.tasks == {}
    assert cfg.database.dsn == DEFAULT_DSN
    assert cfg.budget.monthly_usd == 5.0
    with pytest.raises(ConfigError):
        cfg.task("agent")


@pytest.mark.parametrize(
    "data",
    [
        {"providers": {"openai": {"keys": ["sk-proj-abcdefghijklmnop"]}}},
        {"providers": {"gemini": {"keys": ["AIzaSyA1234567890abcdefghijklmnop"]}}},
        {"providers": {"openai": {"keys": ["k1"], "api_key": "x"}}},
        {"providers": {"openai": {"keys": ["nome com espaço"]}}},
        {"providers": {"openai": {"keys": "openai-1"}}},
        {"providers": {}, "tasks": {"agent": {"provider": "openai", "model": "m"}}},
        {"providers": {"openai": {"keys": []}}, "tasks": {"agent": {"provider": "openai"}}},
        {"database": {"password": "x"}},
        {"budget": {"monthly_usd": -1}},
    ],
)
def test_invalid_config(data):
    with pytest.raises(ConfigError):
        parse_config(data)


def test_missing_and_broken_file(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nada.toml")
    bad = tmp_path / "bad.toml"
    bad.write_text("[providers\n")
    with pytest.raises(ConfigError):
        load_config(bad)


# --- recarga ----------------------------------------------------------------


async def test_reload_keeps_last_good(tmp_path):
    p = tmp_path / "config.toml"
    p.write_bytes(EXAMPLE.read_bytes())
    w = ConfigWatcher(p)
    seen = []
    w.on_reload(seen.append)

    p.write_text(EXAMPLE.read_text().replace("monthly_usd = 5.0", "monthly_usd = 7.5"))
    assert await w.reload() is True
    assert w.current.budget.monthly_usd == 7.5 and len(seen) == 1

    p.write_text("[providers\n")
    assert await w.reload() is False
    assert w.current.budget.monthly_usd == 7.5 and len(seen) == 1


async def test_watcher_reloads_on_save(tmp_path):
    p = tmp_path / "config.toml"
    p.write_bytes(EXAMPLE.read_bytes())
    w = ConfigWatcher(p)
    got = asyncio.Event()

    async def cb(cfg):
        if cfg.budget.monthly_usd == 9.0:
            got.set()

    w.on_reload(cb)
    stop = asyncio.Event()
    task = asyncio.create_task(w.run(stop))
    try:
        await asyncio.sleep(0.3)  # deixa o inotify armar
        # salva como um editor: escreve num temporário e renomeia
        tmp = tmp_path / ".config.toml.swp"
        tmp.write_text(EXAMPLE.read_text().replace("monthly_usd = 5.0", "monthly_usd = 9.0"))
        tmp.replace(p)
        await asyncio.wait_for(got.wait(), timeout=10)
        assert w.current.budget.monthly_usd == 9.0
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=5)


# --- segredos ---------------------------------------------------------------


def test_secrets_roundtrip(fake_keyring):
    assert secrets.get_secret("openai-1") is None
    assert not secrets.has_secret("openai-1")
    secrets.set_secret("openai-1", "  valor-secreto\n")
    assert secrets.get_secret("openai-1") == "valor-secreto"
    assert fake_keyring.store == {(secrets.SERVICE, "openai-1"): "valor-secreto"}
    assert secrets.require_secret("openai-1") == "valor-secreto"
    assert secrets.delete_secret("openai-1") is True
    assert secrets.delete_secret("openai-1") is False
    with pytest.raises(secrets.SecretError):
        secrets.require_secret("openai-1")


@pytest.mark.parametrize("name", ["", "com espaço", "a/b", "-x"])
def test_secret_name_validation(name):
    with pytest.raises(secrets.SecretError):
        secrets.set_secret(name, "v")


def test_empty_secret_rejected():
    with pytest.raises(secrets.SecretError):
        secrets.set_secret("openai-1", "  \n")


# --- magi-keys ---------------------------------------------------------------


def test_cli_add_list_remove(monkeypatch, tmp_path, capsys, fake_keyring):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO("chave-do-teste\n"))
    assert keys_cli.main(["add", "openai-1"]) == 0
    assert fake_keyring.store[(secrets.SERVICE, "openai-1")] == "chave-do-teste"

    # não sobrescreve sem --force
    monkeypatch.setattr("sys.stdin", io.StringIO("outra\n"))
    assert keys_cli.main(["add", "openai-1"]) == 1
    assert keys_cli.main(["add", "openai-1", "--force"]) == 0
    assert secrets.get_secret("openai-1") == "outra"

    capsys.readouterr()
    assert keys_cli.main(["list", "--config", str(EXAMPLE)]) == 1  # faltam as outras
    out = capsys.readouterr().out
    assert re.search(r"openai-1\s+ok", out) and re.search(r"gemini-1\s+FALTA", out)
    assert "outra" not in out

    assert keys_cli.main(["remove", "openai-1"]) == 0
    assert keys_cli.main(["remove", "openai-1"]) == 1
    # nada de segredo gravado em arquivo
    assert list(tmp_path.iterdir()) == []


def test_cli_invalid_name(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("v\n"))
    assert keys_cli.main(["add", "nome inválido"]) == 1
