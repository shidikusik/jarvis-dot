"""Exact prerecorded responses from an explicitly imported local sound pack."""
from pathlib import Path
import sys

from jarvis.commands import normalize

PHRASES = {
    "к вашим услугам сэр": "ready.wav",
    "всегда к вашим услугам сэр": "ready.wav",
    "запрос выполнен сэр": "done.wav",
    "готово": "done.wav",
    "как пожелаете": "ack.wav",
    "да сэр": "yes.wav",
    "загружаю сэр": "loading.wav",
    "мы подключены и готовы": "connected.wav",
    "проверка завершена": "check.wav",
}


def pack_root():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])) / "assets/jarvis_pack"


def recorded_reply(text):
    name = PHRASES.get(normalize(text))
    path = pack_root() / name if name else None
    return path if path and path.is_file() else None
