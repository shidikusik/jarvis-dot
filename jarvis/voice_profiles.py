"""Offline male neural speech and character-inspired DSP profiles."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import wave

import numpy as np

VOICE_MODES = {
    "jarvis": {"title": "Jarvis · спокойный и чёткий", "pitch": .96, "length": .98},
    "ultron": {"title": "Ultron · низкий и металлический", "pitch": .80, "length": .93},
}


def voice_assets():
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    root = base / "models/voice"
    binary = root / "piper" / ("piper.exe" if sys.platform == "win32" else "piper")
    model = root / "ru_RU-denis-medium.onnx"
    if not binary.is_file() or not model.is_file() or not model.with_suffix(".onnx.json").is_file():
        return None
    return binary, model


def read_wav(path):
    with wave.open(str(path), "rb") as wav:
        if wav.getsampwidth() != 2:
            raise ValueError("Нужен PCM WAV 16-bit")
        rate, channels = wav.getframerate(), wav.getnchannels()
        audio = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(np.float32) / 32768.
        if channels > 1:
            audio = audio.reshape(-1, channels).mean(axis=1)
        return audio, rate


def write_wav(path, audio, rate):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes((np.clip(audio, -1, 1)*32767).astype("<i2").tobytes())


def process_voice(audio, rate, mode):
    profile = VOICE_MODES[mode]
    if not len(audio):
        return audio.astype(np.float32)
    positions = np.arange(0, len(audio)-1, profile["pitch"])
    shifted = np.interp(positions, np.arange(len(audio)), audio).astype(np.float32)
    output = shifted.copy()
    if mode == "jarvis":
        # Gentle presence and a very short reflection, preserve intelligibility.
        output[1:] += .12 * (shifted[1:] - shifted[:-1])
        delay = int(rate*.021)
        if len(output) > delay:
            output[delay:] += .055 * shifted[:-delay]
    else:
        # Deeper pitch, parallel ring modulation, short metallic reflections.
        carrier = np.sin(2*np.pi*43*np.arange(len(output))/rate)
        output *= .91 + .09*carrier
        for seconds, mix in ((.028, .20), (.061, .10)):
            delay = int(rate*seconds)
            if len(output) > delay:
                output[delay:] += mix*shifted[:-delay]
        output = np.tanh(output*1.18)
    peak = np.max(np.abs(output))
    if peak > 0:
        output *= min(1.25, .90/peak)
    return output.astype(np.float32)


def synthesize(text, mode, destination: Path):
    assets = voice_assets()
    if assets is None:
        raise RuntimeError("Нейроголос не установлен. Запустите scripts/download_voices.py или используйте готовую сборку")
    binary, model = assets
    profile = VOICE_MODES[mode]
    with tempfile.TemporaryDirectory(prefix="jarvis-voice-") as temporary:
        raw = Path(temporary) / "raw.wav"
        args = [str(binary), "--model", str(model), "--output_file", str(raw), "--length_scale", str(profile["length"]), "--noise_scale", ".5", "--noise_w", ".65"]
        result = subprocess.run(args, input=text.encode("utf-8"), capture_output=True, timeout=45,
                                cwd=binary.parent,
                                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        if result.returncode or not raw.exists():
            raise RuntimeError(result.stderr.decode("utf-8", errors="replace")[-500:] or "Piper не создал звук")
        audio, rate = read_wav(raw)
        output = process_voice(audio, rate, mode)
        destination.parent.mkdir(parents=True, exist_ok=True)
        write_wav(destination, output, rate)
        return output, rate
