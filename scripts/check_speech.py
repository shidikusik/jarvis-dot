"""Exercise real neural synthesis, DSP and Vosk without network or microphone."""
import json
from pathlib import Path
import sys
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jarvis.commands import defaults, match_phrase
from jarvis.models import MODEL_NAME
from jarvis.voice_profiles import synthesize


def main():
    from vosk import Model, KaldiRecognizer, SetLogLevel
    SetLogLevel(-1)
    model = Model(str(ROOT / "models" / MODEL_NAME))
    path = ROOT / "build/recognition.wav"
    synthesize("Который час", "jarvis", path)
    with wave.open(str(path), "rb") as wav:
        recognizer = KaldiRecognizer(model, wav.getframerate())
        recognizer.AcceptWaveform(wav.readframes(wav.getnframes()))
        text = json.loads(recognizer.FinalResult())["text"]
    match = match_phrase(text, defaults(), require_wake_word=False)
    if not match.commands or match.commands[0]["id"] != "time":
        raise RuntimeError(f"Offline recognition failed: {text!r}")
    print("Real offline speech synthesis + Vosk recognition: PASS", flush=True)
    for mode in ("jarvis", "ultron"):
        synthesize("Добрый вечер. Все системы готовы. Ожидаю ваших команд.", mode, ROOT / "docs/audio" / f"{mode}.wav")
        print("Voice profile:", mode, "PASS", flush=True)


if __name__ == "__main__":
    main()
