"""Install the verified speech model into the source/bundle models directory."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jarvis.models import install_model

if __name__ == "__main__":
    print(install_model(ROOT, lambda p: print(f"Model: {p}%", flush=True)))
