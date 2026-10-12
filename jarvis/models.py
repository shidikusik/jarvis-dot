from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import sys
import tempfile
import urllib.request
import zipfile

MODEL_NAME = "vosk-model-small-ru-0.22"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
# Set to the verified upstream archive digest in the release source.
MODEL_SHA256 = "961d5ff98a17f4aa6de69864d0aa71fa5bac682301d2b5d17a3f24c5c99a46d4"


def valid_model(path: Path) -> bool:
    return (path / "am/final.mdl").is_file() and (path / "conf/model.conf").is_file()


def find_model(settings, root: Path) -> Path | None:
    custom = settings.get("model_path")
    candidates = [Path(custom).expanduser()] if custom else []
    candidates += [root / "models" / MODEL_NAME,
                   Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])) / "models" / MODEL_NAME]
    return next((p for p in candidates if valid_model(p)), None)


def safe_extract(archive: Path, destination: Path):
    with zipfile.ZipFile(archive) as z:
        total = 0
        for entry in z.infolist():
            normalized = entry.filename.replace("\\", "/")
            target = (destination / normalized).resolve()
            if not target.is_relative_to(destination.resolve()) or normalized.startswith("/") or ":" in normalized:
                raise ValueError("Недопустимый путь в архиве модели")
            if ((entry.external_attr >> 16) & 0o170000) == 0o120000:
                raise ValueError("Символьные ссылки в архиве не поддерживаются")
            total += entry.file_size
            if total > 512 * 1024 * 1024:
                raise ValueError("Архив модели слишком большой")
        z.extractall(destination)


def install_model(root: Path, progress=lambda percent: None):
    parent = root / "models"
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / MODEL_NAME
    if valid_model(target):
        return target
    with tempfile.TemporaryDirectory(prefix=".download-", dir=parent) as temp:
        staging = Path(temp)
        archive = staging / "model.zip"
        digest, downloaded = hashlib.sha256(), 0
        request = urllib.request.Request(MODEL_URL, headers={"User-Agent": "JarvisDot/0.1"})
        with urllib.request.urlopen(request, timeout=30) as response, archive.open("wb") as output:
            total = int(response.headers.get("Content-Length", 0))
            while block := response.read(256 * 1024):
                downloaded += len(block)
                if downloaded > 100 * 1024 * 1024:
                    raise ValueError("Размер загрузки превысил лимит")
                digest.update(block)
                output.write(block)
                progress(min(99, int(downloaded * 100 / total)) if total else 0)
        if digest.hexdigest() != MODEL_SHA256:
            raise ValueError("Контрольная сумма модели не совпала. Файл не установлен")
        safe_extract(archive, staging)
        extracted = staging / MODEL_NAME
        if not valid_model(extracted):
            raise ValueError("Архив не содержит рабочую модель")
        if target.exists():
            # Replace only the known invalid model directory, preserve all other data.
            backup = parent / (MODEL_NAME + ".invalid")
            if backup.exists():
                raise ValueError(f"Переместите старую модель вручную: {target}")
            target.rename(backup)
        shutil.move(str(extracted), str(target))
    progress(100)
    return target
