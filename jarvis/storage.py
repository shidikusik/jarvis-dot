from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import sys
import tempfile


def data_directory() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "JarvisDot"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "jarvis-dot"


DEFAULT_SETTINGS = {
    "wake_word": "джарвис",
    "require_wake_word": True,
    "spoken_replies": True,
    "voice_mode": "jarvis",
    "use_voice_pack": True,
    "clone_enabled": False,
    "clone_python": "",
    "clone_model": "",
    "accent": "#d9e7a5",
    "model_path": "",
    "microphone": None,
    "recognition_backend": "offline",
    "speech_threshold": 0.004,
    "min_recognition_confidence": 0.72,
    "close_to_tray": True,
}


class Store:
    def __init__(self, root: Path | None = None):
        self.root = root or data_directory()
        self.root.mkdir(parents=True, exist_ok=True)

    def read(self, name: str, fallback):
        path = self.root / name
        if not path.exists():
            return copy.deepcopy(fallback)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"Не удалось прочитать {path}. Сохраните копию и исправьте JSON: {exc}") from exc

    def write(self, name: str, value):
        payload = json.dumps(value, ensure_ascii=False, indent=2)
        fd, temp = tempfile.mkstemp(prefix=".save-", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, self.root / name)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def settings(self):
        return DEFAULT_SETTINGS | self.read("settings.json", {})

    def history(self):
        return self.read("history.json", [])

    def record(self, entry):
        entries = self.history()
        entries.insert(0, entry)
        self.write("history.json", entries[:100])
