"""Install checksum-pinned standalone Piper (MIT legacy engine) and male RU voice."""
from pathlib import Path
import hashlib
import shutil
import sys
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jarvis.models import safe_extract

RELEASE = "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/"
HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/denis/medium/"
FILES = [
    ("ru_RU-denis-medium.onnx", HF, "15fab56e11a097858ee115545d0f697fc2a316c41a291a5362349fb870411b0a"),
    ("ru_RU-denis-medium.onnx.json", HF, "831c860dac0b5073eaa81610a0a638ec23d90a6cf8e5f871b4485c2cec3767c8"),
    ("MODEL_CARD", HF, "8b5d685dd80f8ad3f8dbbe1c56b16bb0809f00c144af3642dbcf3b707eb89c12"),
]


def verified(path, digest):
    return path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest


def download(url, path, digest):
    if verified(path, digest):
        return
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
        staging = Path(output.name)
        try:
            print("Downloading", path.name, flush=True)
            with urllib.request.urlopen(url, timeout=45) as response:
                while block := response.read(256*1024):
                    output.write(block)
            output.close()
            if not verified(staging, digest):
                raise ValueError(f"Checksum mismatch: {path.name}")
            staging.replace(path)
        finally:
            output.close()
            staging.unlink(missing_ok=True)


def install():
    target = ROOT / "models/voice"
    target.mkdir(parents=True, exist_ok=True)
    for name, base, digest in FILES:
        cached = ROOT / "models" / ("denis-MODEL_CARD" if name == "MODEL_CARD" else name)
        if verified(cached, digest) and not verified(target/name, digest):
            shutil.copy2(cached, target/name)
        download(base+name, target/name, digest)
    windows = sys.platform == "win32"
    name = "piper_windows_amd64.zip" if windows else "piper_linux_x86_64.tar.gz"
    digest = "f3c58906402b24f3a96d92145f58acba6d86c9b5db896d207f78dc80811efcea" if windows else "a50cb45f355b7af1f6d758c1b360717877ba0a398cc8cbe6d2a7a3a26e225992"
    archive = ROOT / "models" / name
    download(RELEASE+name, archive, digest)
    if windows:
        safe_extract(archive, target)
    else:
        with tarfile.open(archive) as tar:
            tar.extractall(target, filter="data")
    binary = target / "piper" / ("piper.exe" if windows else "piper")
    if not binary.is_file():
        raise RuntimeError(f"Piper executable missing: {binary}")
    print("Offline neural voices ready:", target, flush=True)


if __name__ == "__main__":
    install()
