"""Run optional voice conversion in an isolated local Python environment."""
import hashlib
from pathlib import Path
import subprocess
import sys

from jarvis.packs import pack_root
from jarvis.storage import data_directory
from jarvis.voice_profiles import synthesize


def clone_reply(text, config, temporary):
    python = Path(config["clone_python"])
    model = Path(config["clone_model"])
    if not python.is_file() or not (model/"s3gen.safetensors").is_file():
        raise RuntimeError("Не найден локальный движок клонирования. Проверьте пути в настройках")
    reference = pack_root()/"reference.wav"
    if not reference.is_file():
        raise RuntimeError("Не найден образец голоса из пака")
    cache = data_directory()/"voice_cache"
    cache.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256((text + "|clone-v1|").encode() + reference.read_bytes()).hexdigest()
    destination = cache/(key+".wav")
    if destination.is_file():
        return destination
    raw = temporary/"base.wav"
    synthesize(text, "jarvis", raw)
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    args = [str(python), str(base/"scripts/clone_voice.py"), "--input", str(raw),
            "--reference", str(reference), "--model", str(model), "--output", str(destination)]
    result = subprocess.run(args, capture_output=True, timeout=150,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    if result.returncode or not destination.is_file():
        raise RuntimeError("Клонирование голоса: " + result.stderr.decode("utf-8", errors="replace")[-1000:])
    # Keep the local cache bounded to the most recent 200 synthesized replies.
    for old in sorted(cache.glob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)[200:]:
        old.unlink()
    return destination
