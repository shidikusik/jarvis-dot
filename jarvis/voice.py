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

    def __init__(self, model_path: Path, microphone, speaking: threading.Event,
                 settings=None, cloud_transcriber=None):
        super().__init__()
        self.model_path, self.microphone, self.speaking = model_path, microphone, speaking
        self.settings = dict(settings or {})
        self.cloud_transcriber = cloud_transcriber
        self.stop_event = threading.Event()
        self.suspended = threading.Event()
        self.transcribing = threading.Event()

    def stop(self):
        self.stop_event.set()

    def _trusted_text(self, result):
        """No low-confidence or unknown local guesses become executable text."""
        text = result.get("text", "").strip()
        words = result.get("result", [])
        if not text or "[unk]" in text or not words:
            return ""
        confidence = [float(word.get("conf", 0)) for word in words]
        threshold = float(self.settings.get("min_recognition_confidence", .72))
        if (not all(math.isfinite(value) for value in confidence)
                or min(confidence) < .40
                or sum(confidence) / len(confidence) < threshold):
            return ""
        return text

    def _wake_is_confident(self, result):
        from jarvis.commands import normalize
        wake = normalize(self.settings.get("wake_word", "джарвис"))
        text = normalize(result.get("text", ""))
        words = result.get("result", [])
        prefix = wake.split()
        if not prefix or not (text == wake or text.startswith(wake + " ")):
            return False
        if len(words) < len(prefix):
            return False
        threshold = float(self.settings.get("min_recognition_confidence", .72))
        for expected, actual in zip(prefix, words):
            confidence = float(actual.get("conf", 0))
            if (normalize(actual.get("word", "")) != expected
                    or not math.isfinite(confidence) or confidence < threshold):
                return False
        return True

    def _finish_utterance(self, pcm, sample_rate, result, wake_result=None, verification_result=None):
        from jarvis.commands import normalize
        if self.stop_event.is_set() or self.suspended.is_set() or self.speaking.is_set():
            return
        use_cloud = (self.cloud_transcriber is not None
                     and self.settings.get("recognition_backend", "offline") == "gemini")
        # The local opt-out is useful for push-to-talk/offline commands. Cloud
        # requests always require an explicitly addressed, confident local wake.
        require_wake = use_cloud or self.settings.get("require_wake_word", True)
        acoustic_result = wake_result if wake_result is not None else result
        cancelled = {"не", "нет", "отмена", "отмени", "стоп"}
        transcripts = [result, acoustic_result, verification_result or {}]
        if any(cancelled.intersection(normalize(r.get("text", "")).split()) for r in transcripts):
            self.state.emit("Команда отменена.")
            return
        wake_valid = self._wake_is_confident(wake_result if wake_result is not None else result)
        if require_wake and not wake_valid:
            return
        local_text = self._trusted_text(result)
        if use_cloud:
            self.transcribing.set()
            self.state.emit("Распознаю команду онлайн…")
            try:
                # Audio stays local until its locally recognized wake prefix is
                # confident, including when offline wake gating is disabled.
                completed = threading.Event()
                outcome = {}

                def request():
                    try:
                        outcome["text"] = self.cloud_transcriber(pcm, sample_rate, result.get("text", ""))
                    except Exception:
                        outcome["failed"] = True
                    finally:
                        completed.set()

                threading.Thread(target=request, daemon=True).start()
                deadline = time.monotonic() + 35
                while not completed.wait(.05):
                    if self.stop_event.is_set() or self.suspended.is_set() or self.speaking.is_set():
                        return
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Cloud recognition timed out")
                if outcome.get("failed"):
                    raise RuntimeError("Cloud recognition unavailable")
                text = outcome.get("text", "")
                if self.stop_event.is_set() or self.suspended.is_set() or self.speaking.is_set():
                    return
                if not isinstance(text, str) or not text.strip():
                    self.state.emit("Не разобрал команду. Повторите ближе к микрофону.")
                    return
                text = normalize(text[:1000])
                if require_wake:
                    wake = normalize(self.settings.get("wake_word", "джарвис"))
                    if text != wake and not text.startswith(wake + " "):
                        text = wake + " " + text
                self.recognized.emit(text)
                return
            except Exception:
                # Provider errors can contain URLs or credentials. Emit a fixed
                # status and preserve safe offline command execution instead.
                self.state.emit("Онлайн-распознавание недоступно. Использую локальное.")
            finally:
                self.transcribing.clear()
        if local_text:
            self.recognized.emit(local_text)
        else:
            self.state.emit("Не разобрал команду. Повторите ближе к микрофону.")

    def _grammar(self):
        from jarvis.commands import defaults, normalize
        wake = normalize(self.settings.get("wake_word", "джарвис"))
        phrases = self.settings.get("command_phrases")
        if phrases is None:
            phrases = [p for command in defaults() for p in command["phrases"]]
        phrases = [normalize(p) for p in phrases if isinstance(p, str) and normalize(p)]
        # [unk] gives unrelated speech a rejection path, instead of forcing it
        # into one of the configured commands. Connectors retain chained actions.
        grammar = ["[unk]", "и затем", "затем", "и", "не", "нет", "отмена", "отмени", "стоп", "не надо"]
        if wake:
            grammar.append(wake)
        for phrase in phrases:
            grammar.append(phrase)
            if wake:
                grammar.append(wake + " " + phrase)
        return json.dumps(list(dict.fromkeys(grammar)), ensure_ascii=False)

    def run(self):
        try:
            import numpy as np
            import sounddevice as sd
            from vosk import Model, KaldiRecognizer, SetLogLevel
            from jarvis.audio_gate import SpeechGate
            SetLogLevel(-1)
            self.state.emit("Загружаю локальную модель…")
            model = Model(str(self.model_path))
            device = sd.query_devices(self.microphone, "input")
            capture_rate = 16000
            try:
                sd.check_input_settings(device=self.microphone, channels=1,
                                        dtype="int16", samplerate=capture_rate)
            except (sd.PortAudioError, ValueError):
                capture_rate = int(device["default_samplerate"])
                sd.check_input_settings(device=self.microphone, channels=1,
                                        dtype="int16", samplerate=capture_rate)
            sample_rate = 16000
            use_cloud = (self.cloud_transcriber is not None
                         and self.settings.get("recognition_backend", "offline") == "gemini")
            # Free-form decoding is necessary for a trustworthy cloud wake gate.
            # Command grammar improves the much smaller offline command domain.
            if use_cloud:
                recognizer = KaldiRecognizer(model, sample_rate)
            else:
                try:
                    recognizer = KaldiRecognizer(model, sample_rate, self._grammar())
                except Exception:
                    self.state.emit("Модель без словаря команд. Использую обычное локальное распознавание.")
                    recognizer = KaldiRecognizer(model, sample_rate)
            recognizer.SetWords(True)
            # A constrained decoder may discard unknown words before the wake
            # name. Independently verify the true beginning of addressed offline
            # phrases with the complete vocabulary before accepting its command.
            wake_verifier = None
            if not use_cloud:
                wake_verifier = KaldiRecognizer(model, sample_rate)
                wake_verifier.SetWords(True)
            safety_verifier = None
            if use_cloud:
                try:
                    safety_verifier = KaldiRecognizer(model, sample_rate, self._grammar())
                    safety_verifier.SetWords(True)
                except Exception:
                    pass
            gate = SpeechGate(sample_rate, threshold=self.settings.get("speech_threshold", .004))
            audio = queue.Queue(maxsize=50)
            overrun = threading.Event()
            paused_capture = threading.Event()

            def callback(data, frames, timing, status):
                if (self.stop_event.is_set() or self.speaking.is_set()
                        or self.suspended.is_set() or self.transcribing.is_set()
                        or paused_capture.is_set()):
                    return
                if status:
                    overrun.set()
                try:
                    audio.put_nowait(bytes(data))
                except queue.Full:
                    overrun.set()

            results = []
            pause_was_active = False
            resume_after = 0.
            partial_after = 0.

            def reset_capture():
                gate.reset()
                recognizer.Reset()
                results.clear()
                while True:
                    try:
                        audio.get_nowait()
                    except queue.Empty:
                        break
                self.partial.emit("")

            with sd.RawInputStream(samplerate=capture_rate, blocksize=int(capture_rate * .02),
                    dtype="int16", channels=1, device=self.microphone, callback=callback):
                wake = self.settings.get("wake_word", "джарвис")
                self.state.emit(f"Слушаю. Скажите «{wake.capitalize()}» и команду" if self.settings.get("require_wake_word", True) else "Слушаю команду.")
                while not self.stop_event.is_set():
                    paused = self.speaking.is_set() or self.suspended.is_set()
                    if paused:
                        if not pause_was_active:
                            reset_capture()
                            self.level.emit(0)
                        pause_was_active = True
                        self.stop_event.wait(.03)
                        continue
                    if pause_was_active:
                        reset_capture()
                        resume_after = time.monotonic() + .35
                        pause_was_active = False
                    if overrun.is_set():
                        overrun.clear()
                        reset_capture()
                        self.state.emit("Пропуск аудио. Повторите команду.")
                    try:
                        data = audio.get(timeout=.2)
                    except queue.Empty:
                        continue
                    if time.monotonic() < resume_after:
                        continue
                    if capture_rate != sample_rate:
                        samples = np.frombuffer(data, dtype="<i2")
                        count = round(len(samples) * sample_rate / capture_rate)
                        positions = np.arange(count) * capture_rate / sample_rate
                        data = np.interp(positions, np.arange(len(samples)), samples).astype("<i2").tobytes()
                    for event in gate.feed(data):
                        self.level.emit(event.level)
                        if event.started:
                            recognizer.Reset()
                            results.clear()
                        if event.rejected:
                            recognizer.Reset()
                            results.clear()
                            self.partial.emit("")
                            continue
                        if event.audio:
                            if recognizer.AcceptWaveform(event.audio):
                                results.append(json.loads(recognizer.Result()))
                            elif time.monotonic() >= partial_after:
                                partial_after = time.monotonic() + .15
                                self.partial.emit(json.loads(recognizer.PartialResult()).get("partial", ""))
                        if event.utterance is not None:
                            results.append(json.loads(recognizer.FinalResult()))
                            result = {"text": " ".join(r.get("text", "") for r in results).strip(),
                                      "result": [word for r in results for word in r.get("result", [])]}
                            paused_capture.set()
                            try:
                                wake_result = None
                                if wake_verifier is not None and self._trusted_text(result):
                                    wake_verifier.Reset()
                                    wake_verifier.AcceptWaveform(event.utterance)
                                    wake_result = json.loads(wake_verifier.FinalResult())
                                verification_result = None
                                if safety_verifier is not None and self._wake_is_confident(result):
                                    safety_verifier.Reset()
                                    safety_verifier.AcceptWaveform(event.utterance)
                                    verification_result = json.loads(safety_verifier.FinalResult())
                                self._finish_utterance(event.utterance, sample_rate, result, wake_result,
                                                       verification_result)
                            finally:
                                reset_capture()
                                resume_after = time.monotonic() + .15
                                paused_capture.clear()
                            break
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
