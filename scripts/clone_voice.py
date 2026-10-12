"""Local reference voice conversion. This process never downloads models."""
import argparse
import os
from pathlib import Path
import time

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    args = parser.parse_args()
    import torch
    import soundfile as sf
    # The top-level package imports unrelated TTS/Gradio functionality. Load the
    # installed VC package namespace alone; no source files are modified.
    import importlib.metadata
    import sys
    import types
    package = types.ModuleType("chatterbox")
    package.__path__ = [str(importlib.metadata.distribution("chatterbox-tts").locate_file("chatterbox"))]
    sys.modules["chatterbox"] = package
    from chatterbox.vc import ChatterboxVC
    device = ("cuda" if torch.cuda.is_available() else "cpu") if args.device == "auto" else args.device
    torch.set_num_threads(min(8, os.cpu_count() or 4))
    started = time.monotonic()
    model = ChatterboxVC.from_local(args.model, device=device)
    wav = model.generate(str(args.input), target_voice_path=str(args.reference))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(args.output), wav.squeeze().numpy(), model.sr, subtype="PCM_16")
    print(f"Local voice conversion: {device}, {time.monotonic()-started:.1f}s, {args.output}", flush=True)


if __name__ == "__main__":
    main()
