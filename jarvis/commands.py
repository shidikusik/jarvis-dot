from __future__ import annotations

from dataclasses import dataclass
import re
import uuid

ACTION_TYPES = {"open_app", "open_url", "open_folder", "media", "wait", "speak", "time", "note", "lock"}
MEDIA_ACTIONS = {"volume_up", "volume_down", "mute", "play_pause", "next", "previous"}


def normalize(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.casefold().replace("ё", "е")).split())


def validate_command(command: dict) -> dict:
    if not isinstance(command, dict):
        raise ValueError("Команда должна быть объектом")
    if not isinstance(command.get("title"), str) or not command["title"].strip():
        raise ValueError("Введите название")
    phrases = command.get("phrases")
    if not isinstance(phrases, list) or not phrases or any(not isinstance(p, str) or not normalize(p) for p in phrases):
        raise ValueError("Нужна хотя бы одна непустая фраза")
    actions = command.get("actions")
    if not isinstance(actions, list) or not 1 <= len(actions) <= 40:
        raise ValueError("В сценарии должно быть от 1 до 40 действий")
    for action in actions:
        if not isinstance(action, dict) or action.get("type") not in ACTION_TYPES:
            raise ValueError("Неизвестное действие")
        kind = action["type"]
        value = action.get("value", "")
        if not isinstance(value, str):
            raise ValueError("Значение действия должно быть строкой")
        if kind == "media" and value not in MEDIA_ACTIONS:
            raise ValueError("Выберите поддерживаемое управление звуком")
        if kind == "wait":
            try:
                seconds = float(value)
            except ValueError as exc:
                raise ValueError("Пауза должна быть числом") from exc
            if not 0 <= seconds <= 30:
                raise ValueError("Пауза: от 0 до 30 секунд")
        if kind in {"open_url", "open_folder", "speak", "note"} and not value.strip():
            raise ValueError("Заполните значение действия")
        if kind == "open_url":
            from urllib.parse import urlsplit
            url = urlsplit(value)
            if url.scheme not in {"http", "https"} or not url.hostname:
                raise ValueError("Сайт должен начинаться с http:// или https://")
        if kind == "open_app":
            if any(not isinstance(action.get(platform, ""), str) for platform in ("windows", "linux")):
                raise ValueError("Путь программы должен быть строкой")
            if not any(action.get(platform, "").strip() for platform in ("windows", "linux")):
                raise ValueError("Укажите программу для Windows или Linux")
    return {
        "id": str(command.get("id") or uuid.uuid4()),
        "title": command["title"].strip(),
        "phrases": list(dict.fromkeys(p.strip() for p in phrases)),
        "actions": actions,
        "enabled": bool(command.get("enabled", True)),
        "confirm": bool(command.get("confirm", False)) or any(a["type"] == "lock" for a in actions),
    }


def validate_collection(commands):
    if not isinstance(commands, list) or len(commands) > 500:
        raise ValueError("Ожидается список, не более 500 команд")
    result = [validate_command(c) for c in commands]
    ids, phrases = set(), set()
    for c in result:
        if c["id"] in ids:
            raise ValueError("Повторяющийся ID команды")
        ids.add(c["id"])
        if c["enabled"]:
            for p in c["phrases"]:
                n = normalize(p)
                if n in phrases:
                    raise ValueError(f"Фраза уже используется: {p}")
                phrases.add(n)
    return result


@dataclass
class Match:
    commands: list[dict]
    reason: str = ""

    @property
    def needs_confirmation(self):
        return any(c.get("confirm") for c in self.commands)


def match_phrase(text: str, commands: list[dict], wake_word="джарвис", require_wake_word=True) -> Match:
    text, prefix = normalize(text), normalize(wake_word)
    if prefix and (text == prefix or text.startswith(prefix + " ")):
        text = text[len(prefix):].strip()
    elif require_wake_word:
        return Match([], "Скажите имя помощника перед командой")
    index = {normalize(p): c for c in commands if c.get("enabled", True) for p in c["phrases"]}
    if text in index:
        return Match([index[text]])
    # Split only when the entire phrase can be resolved. No fuzzy destructive matches.
    def resolve(rest, depth=0):
        if depth >= 5:
            return None
        if rest in index:
            return [index[rest]]
        for phrase in sorted(index, key=len, reverse=True):
            for separator in (" и затем ", " затем ", " и "):
                start = phrase + separator
                if rest.startswith(start):
                    tail = resolve(rest[len(start):], depth + 1)
                    if tail:
                        return [index[phrase]] + tail
        return None
    found = resolve(text)
    return Match(found or [], "" if found else "Такой команды пока нет. Добавьте её в редакторе")


def defaults():
    def c(key, title, phrases, actions, confirm=False):
        return validate_command(dict(id=key, title=title, phrases=phrases, actions=actions, confirm=confirm))
    return [
        c("time", "Который час", ["который час", "сколько времени", "время"], [{"type": "time"}]),
        c("files", "Открыть файлы", ["открой файлы", "открой проводник"], [{"type": "open_folder", "value": "~"}]),
        c("notes", "Открыть блокнот", ["открой блокнот", "открой заметки"], [{"type": "open_app", "windows": "notepad.exe", "linux": "@text-editor"}]),
        c("up", "Громче", ["громче", "сделай громче"], [{"type": "media", "value": "volume_up"}]),
        c("down", "Тише", ["тише", "сделай тише"], [{"type": "media", "value": "volume_down"}]),
        c("mute", "Выключить звук", ["выключи звук", "включи звук"], [{"type": "media", "value": "mute"}]),
        c("pause", "Пауза / продолжить", ["пауза", "продолжи музыку"], [{"type": "media", "value": "play_pause"}]),
        c("next", "Следующий трек", ["следующий трек"], [{"type": "media", "value": "next"}]),
        c("previous", "Предыдущий трек", ["предыдущий трек"], [{"type": "media", "value": "previous"}]),
        c("work", "Режим работы", ["режим работы"], [{"type": "open_folder", "value": "~"}, {"type": "open_app", "windows": "notepad.exe", "linux": "@text-editor"}, {"type": "speak", "value": "Режим работы готов"}]),
        c("lock", "Заблокировать компьютер", ["заблокируй компьютер"], [{"type": "lock"}], True),
    ]
