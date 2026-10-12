from __future__ import annotations

import json
import math
from pathlib import Path
import queue
import struct
import subprocess
import sys
import threading
import tempfile
import time
import os
import signal

from PySide6.QtCore import QThread, Signal


class Speaker:
    """Isolate platform speech drivers from the GUI and recognition threads."""
    def __init__(self, error=lambda message: None, status=lambda message: None):
        self.error = error
        self.status = status
        self.enabled = True
        self.mode = "jarvis"
        self.use_pack = True
        self.clone_python = ""
        self.clone_model = ""
        self.clone_enabled = False
        self.active = threading.Event()
        self._queue = queue.Queue(maxsize=8)
        self._closing = threading.Event()
        self._process = None
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def say(self, text, force=False, use_pack=None):
        if (self.enabled or force) and not self._closing.is_set():
            try:
                self._queue.put_nowait(dict(text=text, mode=self.mode,
                    use_pack=self.use_pack if use_pack is None else use_pack,
                    clone_python=self.clone_python, clone_model=self.clone_model, clone_enabled=self.clone_enabled))
            except queue.Full:
                pass

    def _run(self):
        while not self._closing.is_set():
            try:
                payload_data = self._queue.get(timeout=.2)
            except queue.Empty:
                continue
            try:
                with tempfile.TemporaryDirectory(prefix="jarvis-speech-") as temporary:
                    payload = Path(temporary) / "speech.json"
                    playing = Path(temporary) / "playing.flag"
                    payload_data["playing_flag"] = str(playing)
                    self.status("Готовлю голос локально…" + (" Перенос новой фразы на CPU может занять около минуты." if payload_data["clone_enabled"] else ""))
                    payload.write_text(json.dumps(payload_data, ensure_ascii=False), encoding="utf-8")
                    args = [sys.executable, "--tts"] if getattr(sys, "frozen", False) else [sys.executable, "-m", "jarvis", "--tts"]
                    args += ["--speech-file", str(payload)]
                    self._process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                        start_new_session=sys.platform != "win32")
                    process = self._process
                    def watch_playback():
                        while process.poll() is None and not self._closing.is_set():
                            if playing.exists():
                                self.active.set()
                            else:
                                self.active.clear()
                            time.sleep(.05)
                    watcher = threading.Thread(target=watch_playback, daemon=True)
                    watcher.start()
                    _, errors = self._process.communicate(timeout=180 if self.clone_enabled else 55)
                    watcher.join(timeout=1)
                    if self._process.returncode:
                        self.error(errors.decode("utf-8", errors="replace")[-500:] or "Голосовой движок недоступен")
                    else:
                        self.status("Озвучивание завершено.")
            except Exception as exc:
                if self._process and self._process.poll() is None:
                    self._terminate(self._process)
                    self._process.communicate()
                if not self._closing.is_set():
                    self.error(f"Озвучивание: {exc}")
            finally:
                self._process = None
                self.active.clear()

    def close(self):
        self._closing.set()
        if self._process and self._process.poll() is None:
            self._terminate(self._process)
        self._worker.join(timeout=2)

    @staticmethod
    def _terminate(process):
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


class Listener(QThread):
    recognized = Signal(str)
    partial = Signal(str)
    state = Signal(str)
    failed = Signal(str)
    level = Signal(float)

    def __init__(self, model_path: Path, microphone, speaking: threading.Event):
        super().__init__()
        self.model_path, self.microphone, self.speaking = model_path, microphone, speaking
        self.stop_event = threading.Event()
        self.suspended = threading.Event()

    def stop(self):
        self.stop_event.set()

    def run(self):
        try:
            import sounddevice as sd
            from vosk import Model, KaldiRecognizer, SetLogLevel
            SetLogLevel(-1)
            self.state.emit("Загружаю локальную модель…")
            model = Model(str(self.model_path))
            device = sd.query_devices(self.microphone, "input")
            sample_rate = int(device["default_samplerate"])
            recognizer = KaldiRecognizer(model, sample_rate)
            audio = queue.Queue(maxsize=30)

            def callback(data, frames, timing, status):
                if self.stop_event.is_set():
                    return
                try:
                    audio.put_nowait(bytes(data))
                except queue.Full:
                    pass

            with sd.RawInputStream(samplerate=sample_rate, blocksize=int(sample_rate * .12),
                    dtype="int16", channels=1, device=self.microphone, callback=callback):
                self.state.emit("Слушаю. Скажите «Джарвис» и команду")
                while not self.stop_event.is_set():
                    try:
                        data = audio.get(timeout=.2)
                    except queue.Empty:
                        continue
                    if self.speaking.is_set() or self.suspended.is_set():
                        recognizer.Reset()
                        self.level.emit(0)
                        continue
                    samples = struct.unpack(f"<{len(data)//2}h", data)
                    rms = math.sqrt(sum(x*x for x in samples) / max(1, len(samples))) / 32768
                    self.level.emit(min(1, rms * 9))
                    if recognizer.AcceptWaveform(data):
                        text = json.loads(recognizer.Result()).get("text", "")
                        if text:
                            self.recognized.emit(text)
                    else:
                        self.partial.emit(json.loads(recognizer.PartialResult()).get("partial", ""))
        except Exception as exc:
            self.failed.emit(f"Микрофон / распознавание: {exc}")
        finally:
            self.level.emit(0)


def speak_process(payload_path):
    payload = json.loads(Path(payload_path).read_text(encoding="utf-8"))
    text, mode = payload["text"], payload.get("mode", "jarvis")
    playing = Path(payload["playing_flag"]) if payload.get("playing_flag") else None
    def play(audio, rate):
        import sounddevice as sd
        try:
            if playing:
                playing.touch()
            sd.play(audio, rate)
            sd.wait()
        finally:
            if playing:
                playing.unlink(missing_ok=True)
    from jarvis.voice_profiles import voice_assets, synthesize, read_wav, process_voice
    from jarvis.packs import recorded_reply, pack_root
    clip = recorded_reply(text) if payload.get("use_pack", True) else None
    if clip:
        import sounddevice as sd
        audio, rate = read_wav(clip)
        if mode == "ultron":
            audio = process_voice(audio, rate, mode)
        play(audio, rate)
        return
    if voice_assets():
        import sounddevice as sd
        with tempfile.TemporaryDirectory(prefix="jarvis-audio-") as temporary:
            if payload.get("clone_enabled") and payload.get("clone_python") and payload.get("clone_model"):
                from jarvis.clone_bridge import clone_reply
                path = clone_reply(text, payload, Path(temporary))
                audio, rate = read_wav(path)
                if mode == "ultron":
                    audio = process_voice(audio, rate, mode)
            else:
                audio, rate = synthesize(text, mode, Path(temporary)/"reply.wav")
            play(audio, rate)
        return
    import pyttsx3
    engine = pyttsx3.init()
    voices = engine.getProperty("voices")
    russian = next((v for v in voices if "ru" in str(v.languages).lower() or any(n in v.name.lower() for n in ("russian", "irina", "pavel"))), None)
    if russian:
        engine.setProperty("voice", russian.id)
    engine.setProperty("rate", 175)
    try:
        if playing:
            playing.touch()
        engine.say(text)
        engine.runAndWait()
    finally:
        if playing:
            playing.unlink(missing_ok=True)
