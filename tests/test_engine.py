import json
from pathlib import Path
import threading
import zipfile

import pytest

from jarvis.commands import defaults, match_phrase, validate_collection, validate_command
from jarvis.models import safe_extract
from jarvis.platform_actions import Executor, launch_app
from jarvis.storage import Store


def test_wake_word_and_full_phrase_only():
    commands = defaults()
    assert not match_phrase("который час", commands).commands
    assert match_phrase("Джарвис, который час!", commands).commands[0]["id"] == "time"
    assert not match_phrase("не джарвис который час", commands).commands
    assert not match_phrase("джарвис не заблокируй компьютер", commands).commands
    assert not match_phrase("джарвис заблокируй", commands).commands


def test_chain_is_atomic_and_requires_confirmation_for_every_dangerous_step():
    commands = defaults()
    match = match_phrase("джарвис который час и затем заблокируй компьютер", commands)
    assert [c["id"] for c in match.commands] == ["time", "lock"]
    assert match.needs_confirmation
    assert not match_phrase("джарвис который час и неизвестная команда", commands).commands


def test_disabled_commands_are_not_matched():
    commands = defaults()
    commands[0]["enabled"] = False
    assert not match_phrase("джарвис который час", commands).commands


@pytest.mark.parametrize("action", [
    {"type": "shell", "value": "anything"},
    {"type": "wait", "value": "nan"},
    {"type": "wait", "value": "31"},
    {"type": "wait", "value": "-1"},
    {"type": "open_url", "value": "file:///etc/passwd"},
    {"type": "open_url", "value": "https://"},
    {"type": "media", "value": "unknown"},
])
def test_invalid_actions_rejected(action):
    with pytest.raises(ValueError):
        validate_command(dict(title="test", phrases=["test"], actions=[action]))


def test_lock_always_requires_confirmation():
    command = validate_command(dict(title="lock", phrases=["lock"], actions=[{"type": "lock"}], confirm=False))
    assert command["confirm"]


def test_duplicate_phrases_rejected():
    commands = defaults()
    commands[1]["phrases"].append("КОТОРЫЙ ЧАС!")
    with pytest.raises(ValueError, match="Фраза уже"):
        validate_collection(commands)


def test_atomic_storage_and_history_cap(tmp_path):
    store = Store(tmp_path)
    store.write("settings.json", {"wake_word": "Джарвис"})
    assert store.settings()["wake_word"] == "Джарвис"
    for n in range(110):
        store.record({"n": n})
    assert len(store.history()) == 100
    assert store.history()[0] == {"n": 109}
    assert not list(tmp_path.glob(".save-*"))


def test_note_action_and_cancellation(tmp_path):
    executor = Executor(tmp_path)
    command = validate_command(dict(title="note", phrases=["note"], actions=[{"type": "note", "value": "Локальная заметка"}]))
    executor.execute([command], threading.Event())
    notes = list((tmp_path / "notes").glob("*.txt"))
    assert notes[0].read_text(encoding="utf-8") == "Локальная заметка"
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(RuntimeError, match="остановлен"):
        executor.execute([command], cancelled)


def test_launch_app_never_uses_shell(monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr("jarvis.platform_actions.subprocess.Popen", lambda args, **kwargs: called.append((args, kwargs)))
    launch_app(dict(windows="notepad.exe", linux="kate"))
    assert called[0][1]["shell"] is False


def test_zip_traversal_blocked(tmp_path):
    archive = tmp_path / "model.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../escape.txt", "bad")
    with pytest.raises(ValueError, match="Недопустимый"):
        safe_extract(archive, tmp_path / "destination")
    assert not (tmp_path / "escape.txt").exists()


def test_no_network_for_local_command(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network must not be used")
    monkeypatch.setattr("socket.socket", forbidden)
    replies = []
    executor = Executor(tmp_path, replies.append)
    match = match_phrase("джарвис который час", defaults())
    executor.execute(match.commands, threading.Event())
    assert replies and replies[0].startswith("Сейчас ")
