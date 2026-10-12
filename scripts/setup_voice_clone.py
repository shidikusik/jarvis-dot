"""Install the optional isolated CPU voice conversion engine and verified weights."""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request
import venv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jarvis.storage import Store

SHA256 = "2b78103c654207393955e4900aac14a12de8ef25f4b09424f1ef91941f161d4e"
URL = "https://huggingface.co/ResembleAI/chatterbox/resolve/main/s3gen.safetensors"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cuda", action="store_true", help="Install CUDA 12.8 PyTorch instead of CPU")
    parser.add_argument("--skip-install", action="store_true")
    args = parser.parse_args()
    environment = ROOT/".voice-venv"
    python = environment/("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        venv.create(environment, with_pip=True)
    if not args.skip_install:
        command = [str(python), "-m", "pip", "install", "torch==2.8.0", "torchaudio==2.8.0"]
        if args.cuda or os.name != "nt":
            index = "https://download.pytorch.org/whl/" + ("cu128" if args.cuda else "cpu")
            command += ["--index-url", index]
        subprocess.run(command, check=True)
        subprocess.run([str(python), "-m", "pip", "install", "chatterbox-tts==0.1.7", "--no-deps"], check=True)
        subprocess.run([str(python), "-m", "pip", "install", "-r", str(ROOT/"requirements-clone.txt")], check=True)
    directory = ROOT/"models/clone"
    directory.mkdir(parents=True, exist_ok=True)
    model = directory/"s3gen.safetensors"
    valid = model.is_file() and hashlib.sha256(model.read_bytes()).hexdigest() == SHA256
    if not valid:
        print("Downloading local voice conversion weights (~1 GB)", flush=True)
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as output:
            staging = Path(output.name)
            try:
                with urllib.request.urlopen(URL, timeout=45) as response:
                    while block := response.read(1024*1024):
                        output.write(block)
                output.close()
                if hashlib.sha256(staging.read_bytes()).hexdigest() != SHA256:
                    raise RuntimeError("Model checksum mismatch")
                staging.replace(model)
            finally:
                output.close()
                staging.unlink(missing_ok=True)
    store = Store()
    settings = store.settings()
    settings.update(clone_python=str(python), clone_model=str(directory), clone_enabled=True)
    store.write("settings.json", settings)
    print("Local voice engine configured. Restart JARVIS DOT.", flush=True)


if __name__ == "__main__":
    main()
