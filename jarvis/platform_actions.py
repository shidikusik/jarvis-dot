from __future__ import annotations

import ctypes
from datetime import datetime
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import threading
import webbrowser

from jarvis.commands import validate_command


class ActionError(RuntimeError):
    pass


def run_checked(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=12,
                                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ActionError(str(exc)) from exc
    if result.returncode:
        raise ActionError(result.stderr.strip() or f"{args[0]}: код {result.returncode}")
    return result.stdout.strip()


def launch_app(action):
    target = action.get("windows" if sys.platform == "win32" else "linux", "").strip()
    if not target:
        raise ActionError("Для этой ОС не указана программа. Откройте редактор команды")
    if target == "@text-editor":
        target = next((p for p in ("gedit", "kate", "gnome-text-editor", "mousepad", "xed", "leafpad", "kwrite") if shutil.which(p)), "")
        if not target:
            raise ActionError("Редактор не найден. Укажите свой редактор в команде «Открыть блокнот»")
    expanded = os.path.expandvars(os.path.expanduser(target))
    if Path(expanded).is_file():
        args = [expanded]
    else:
        args = shlex.split(expanded, posix=sys.platform != "win32")
        if sys.platform == "win32":
            args = [arg.strip('"') for arg in args]
    if not args:
        raise ActionError("Не указана программа")
    try:
        subprocess.Popen(args, shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        raise ActionError(f"Не удалось запустить {args[0]}: {exc}") from exc


def media(value):
    if sys.platform == "win32":
        from ctypes import wintypes
        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]
        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]
        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]
        class UNION(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]
        class INPUT(ctypes.Structure):
            _anonymous_ = ("u",)
            _fields_ = [("type", wintypes.DWORD), ("u", UNION)]
        key = {"mute": 0xAD, "volume_down": 0xAE, "volume_up": 0xAF, "next": 0xB0, "previous": 0xB1, "play_pause": 0xB3}[value]
        events = (INPUT * 2)(INPUT(type=1, ki=KEYBDINPUT(wVk=key)), INPUT(type=1, ki=KEYBDINPUT(wVk=key, dwFlags=2)))
        if ctypes.windll.user32.SendInput(2, events, ctypes.sizeof(INPUT)) != 2:
            raise ActionError("Windows не приняла медиаклавишу")
    elif value in {"play_pause", "next", "previous"}:
        if not shutil.which("playerctl"):
            raise ActionError("Установите playerctl для управления плеером")
        run_checked(["playerctl", {"play_pause": "play-pause", "next": "next", "previous": "previous"}[value]])
    elif shutil.which("wpctl"):
        args = ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"] if value == "mute" else ["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", "5%+" if value == "volume_up" else "5%-"]
        run_checked(args)
    elif shutil.which("pactl"):
        args = ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"] if value == "mute" else ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+5%" if value == "volume_up" else "-5%"]
        run_checked(args)
    else:
        raise ActionError("Не найден wpctl или pactl для управления звуком")


class Executor:
    def __init__(self, root: Path, speak=None):
        self.root, self.speak = root, speak or (lambda text: None)

    def execute(self, commands, cancel: threading.Event, progress=None):
        results = []
        progress = progress or (lambda message: None)
        for command in commands:
            command = validate_command(command)
            for action in command["actions"]:
                if cancel.is_set():
                    raise ActionError("Сценарий остановлен")
                kind, value = action["type"], action.get("value", "")
                progress(f"{command['title']} · {kind}")
                if kind == "open_app":
                    launch_app(action)
                elif kind == "open_url":
                    if not webbrowser.open(value):
                        raise ActionError("Браузер не удалось открыть")
                elif kind == "open_folder":
                    path = Path(value).expanduser().resolve()
                    if not path.is_dir():
                        raise ActionError(f"Папка не найдена: {path}")
                    if sys.platform == "win32":
                        os.startfile(str(path))
                    else:
                        run_checked(["xdg-open", str(path)])
                elif kind == "media":
                    media(value)
                elif kind == "wait":
                    if cancel.wait(float(value)):
                        raise ActionError("Сценарий остановлен")
                elif kind == "speak":
                    self.speak(value)
                    results.append(value)
                elif kind == "time":
                    reply = datetime.now().strftime("Сейчас %H:%M")
                    self.speak(reply)
                    results.append(reply)
                elif kind == "note":
                    note_dir = self.root / "notes"
                    note_dir.mkdir(exist_ok=True)
                    file = note_dir / f"note-{datetime.now():%Y%m%d-%H%M%S-%f}.txt"
                    file.write_text(value, encoding="utf-8")
                    results.append(f"Заметка: {file}")
                elif kind == "lock":
                    if sys.platform == "win32":
                        if not ctypes.windll.user32.LockWorkStation():
                            raise ActionError("Не удалось заблокировать компьютер")
                    else:
                        run_checked(["loginctl", "lock-session"])
            results.append(f"✓ {command['title']}")
        return "\n".join(results)
