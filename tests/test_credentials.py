import os
from pathlib import Path
import stat
import sys

import pytest

from jarvis import credentials
from jarvis.credentials import (CredentialsError, delete_gemini_key,
    has_gemini_key, load_gemini_key, save_gemini_key, validate_gemini_key)


SYNTHETIC_KEY = "AIza" + "x" * 35


@pytest.fixture
def local_store(tmp_path, monkeypatch):
    monkeypatch.setattr(credentials, "data_directory", lambda: tmp_path)
    return tmp_path


def test_missing_key_does_not_create_files(local_store):
    assert load_gemini_key() == ""
    assert not has_gemini_key()
    assert not list(local_store.iterdir())


def test_user_local_round_trip_atomic_replace_and_delete(local_store):
    path = save_gemini_key(SYNTHETIC_KEY)
    assert path == local_store / "credentials" / "gemini.key"
    assert load_gemini_key() == SYNTHETIC_KEY
    assert has_gemini_key()
    another_key = "AIza" + "y" * 35
    assert save_gemini_key(another_key) == path
    assert load_gemini_key() == another_key
    assert not list(path.parent.glob(".key-*"))
    delete_gemini_key()
    assert not has_gemini_key()
    delete_gemini_key()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI requires Windows")
def test_windows_file_contains_dpapi_ciphertext(local_store):
    path = save_gemini_key(SYNTHETIC_KEY)
    contents = path.read_bytes()
    assert contents.startswith(credentials._WINDOWS_MAGIC)
    assert SYNTHETIC_KEY.encode() not in contents
    assert load_gemini_key() == SYNTHETIC_KEY


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions require Linux")
def test_linux_secret_permissions_are_private(local_store):
    path = save_gemini_key(SYNTHETIC_KEY)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    path.chmod(0o644)
    with pytest.raises(CredentialsError, match="только вы"):
        load_gemini_key()
    assert not has_gemini_key()
    save_gemini_key(SYNTHETIC_KEY)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("bad", [None, "", "short", "x" * 300, "AIza" + "x" * 30 + "\nInjected: header"])
def test_invalid_keys_never_expose_input_or_create_files(local_store, bad):
    with pytest.raises(CredentialsError) as raised:
        save_gemini_key(bad)
    if isinstance(bad, str) and len(bad) >= 20:
        assert bad not in str(raised.value)
    assert not list(local_store.iterdir())


def test_outer_whitespace_is_removed():
    assert validate_gemini_key("  " + SYNTHETIC_KEY + "\n") == SYNTHETIC_KEY


def test_corrupt_file_is_sanitized_and_presence_is_false(local_store):
    path = save_gemini_key(SYNTHETIC_KEY)
    path.write_bytes(SYNTHETIC_KEY.encode())
    with pytest.raises(CredentialsError) as raised:
        load_gemini_key()
    assert SYNTHETIC_KEY not in str(raised.value)
    assert not has_gemini_key()


def test_repository_storage_is_rejected(monkeypatch):
    root = Path(credentials.__file__).resolve().parents[1]
    monkeypatch.setattr(credentials, "data_directory", lambda: root / ".secret-test")
    with pytest.raises(CredentialsError, match="папке данных пользователя"):
        save_gemini_key(SYNTHETIC_KEY)
    assert not (root / ".secret-test").exists()


def test_symlink_store_is_rejected(local_store, tmp_path):
    target = tmp_path / "elsewhere"
    target.mkdir()
    directory = local_store / "credentials"
    try:
        directory.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks is unavailable for this Windows account")
    with pytest.raises(CredentialsError, match="ссылкой"):
        save_gemini_key(SYNTHETIC_KEY)
    assert not list(target.iterdir())
