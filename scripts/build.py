"""Build native on the target OS; no cross compilation or browser runtime."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jarvis.models import MODEL_NAME, valid_model


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-model", action="store_true")
    args = parser.parse_args()
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
               "--name", "JarvisDot", "--paths", str(ROOT), "--collect-all", "vosk",
               "--collect-all", "sounddevice", "--collect-submodules", "pyttsx3.drivers"]
    if args.with_model:
        source = ROOT / "models" / MODEL_NAME
        if not valid_model(source):
            raise SystemExit("Run python scripts/download_model.py first")
        command += ["--add-data", f"{source}:models/{MODEL_NAME}"]
        voice = ROOT / "models/voice"
        if not voice.is_dir():
            raise SystemExit("Run python scripts/download_voices.py first")
        command += ["--add-data", f"{voice}:models/voice"]
    command += [str(ROOT / "run.py")]
    command += ["--add-data", f"{ROOT / 'assets'}:assets", "--add-data", f"{ROOT / 'scripts/clone_voice.py'}:scripts"]
    subprocess.run(command, cwd=ROOT, check=True)
    bundle = ROOT / "dist/JarvisDot"
    if sys.platform == "win32":
        # Qt 6.12 imports Windows' unversioned ICU API. A Git installation on PATH
        # can make PyInstaller collect ICU 78 with incompatible suffixed exports.
        # Use the OS ICU provided by supported Windows 10/11 installations.
        for name in ("icuuc.dll", "icudt78.dll"):
            (bundle / "_internal" / name).unlink(missing_ok=True)
    shutil.copy2(ROOT / "README.md", bundle / "README.md")
    shutil.copy2(ROOT / "LICENSE", bundle / "LICENSE")
    shutil.copy2(ROOT / "THIRD_PARTY.md", bundle / "THIRD_PARTY.md")
    if sys.platform == "win32":
        archive = ROOT / "dist/JarvisDot-Windows-x64.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
            for path in bundle.rglob("*"):
                if path.is_file():
                    z.write(path, path.relative_to(bundle.parent))
    else:
        launcher = bundle / "start.sh"
        launcher.write_text('#!/bin/sh\ncd -- "$(dirname -- "$0")" || exit 1\nexec ./JarvisDot "$@"\n', encoding="utf-8")
        launcher.chmod(0o755)
        archive = ROOT / "dist/JarvisDot-Linux-x64.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(bundle, arcname="JarvisDot")
    print(archive)


if __name__ == "__main__":
    main()
