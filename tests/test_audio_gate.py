import json
from pathlib import Path
import threading

import numpy as np
import pytest

from jarvis.audio_gate import SpeechGate
from jarvis.voice import Listener


RATE = 16000
SILENCE = bytes(RATE // 50 * 2)


class EnergyTestVad:
    """Deterministic voice labels; production-classifier tests are separate."""
    def is_speech(self, frame, sample_rate):
        return np.sqrt(np.mean(np.frombuffer(frame, dtype="<i2").astype(float) ** 2)) > 300


def tone(seconds, amplitude=.05, frequency=320):
    audio = amplitude * np.sin(2 * np.pi * frequency * np.arange(round(RATE * seconds)) / RATE)
    return (audio * 32767).astype("<i2").tobytes()


def completed(events):
    return [event.utterance for event in events if event.utterance is not None]


def test_silence_and_short_impulse_do_not_become_utterances():
    gate = SpeechGate(vad=EnergyTestVad())
    audio = SILENCE * 50 + tone(.08) + SILENCE * 50
    assert completed(gate.feed(audio)) == []
    assert not gate.active


def test_phrase_keeps_initial_audio_and_finishes_after_silence():
    gate = SpeechGate(vad=EnergyTestVad())
    speech = tone(.7)
    events = gate.feed(SILENCE * 20 + speech + SILENCE * 40)
    phrases = completed(events)
    assert len(phrases) == 1
    assert speech in phrases[0]
    assert len(phrases[0]) <= (RATE * 2 * 1.1)
    assert sum(event.started for event in events) == 1


def test_arbitrary_input_chunks_and_reset_do_not_join_stale_audio():
    gate = SpeechGate(vad=EnergyTestVad())
    gate.feed(tone(.18) + b"\0")
    assert gate.active
    gate.reset()
    assert not gate.active
    assert completed(gate.feed(SILENCE * 40)) == []
    speech = tone(.5)
    output = []
    stream = speech + SILENCE * 40
    for start in range(0, len(stream), 173):
        output.extend(gate.feed(stream[start:start + 173]))
    assert len(completed(output)) == 1


def test_continuous_speech_is_bounded_and_not_split_into_executable_fragments():
    gate = SpeechGate(vad=EnergyTestVad(), max_utterance_ms=2000)
    events = gate.feed(tone(12))
    assert completed(events) == []
    assert sum(event.rejected for event in events) == 1
    assert not gate.active
    assert len(gate._frames) == 0
    # After a real pause, the next complete sentence works normally.
    assert len(completed(gate.feed(SILENCE * 40 + tone(.5) + SILENCE * 40))) == 1


def test_adaptive_floor_rejects_audio_under_the_ambient_noise_floor():
    class Labels:
        speech = False
        def is_speech(self, frame, sample_rate):
            return self.speech
    labels = Labels()
    gate = SpeechGate(vad=labels)
    gate.feed(tone(3, amplitude=.015))
    assert gate.noise_floor > .008
    labels.speech = True
    assert completed(gate.feed(tone(1, amplitude=.02) + SILENCE * 40)) == []
    assert len(completed(gate.feed(tone(.7, amplitude=.08) + SILENCE * 40))) == 1


@pytest.mark.parametrize("kind", ["white", "hum", "clicks"])
def test_real_webrtc_vad_does_not_transcribe_background_noise(kind):
    pytest.importorskip("webrtcvad")
    gate = SpeechGate()
    if kind == "white":
        audio = np.random.default_rng(19).normal(0, .008, RATE * 4)
    elif kind == "hum":
        times = np.arange(RATE * 4) / RATE
        audio = .045 * np.sin(2 * np.pi * 60 * times) + .015 * np.sin(2 * np.pi * 120 * times)
    else:
        audio = np.zeros(RATE * 4)
        for start in range(RATE // 2, len(audio), RATE // 2):
            audio[start:start + 80] = np.random.default_rng(start).normal(0, .1, 80)
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
    assert completed(gate.feed(pcm + SILENCE * 45)) == []


def local_result(text="джарвис который час", confidence=.96):
    return {"text": text, "result": [{"word": word, "conf": confidence} for word in text.split()]}


def listener(settings=None, transcriber=None):
    instance = Listener(Path("unused-model"), None, threading.Event(), settings, transcriber)
    recognized, states = [], []
    instance.recognized.connect(recognized.append)
    instance.state.connect(states.append)
    return instance, recognized, states


def test_uncertain_or_unknown_local_results_never_emit_commands():
    instance, output, _ = listener()
    for result in (local_result(confidence=.3), local_result("джарвис [unk]"),
                   {"text": "джарвис который час"}, local_result("который час")):
        instance._finish_utterance(b"pcm", RATE, result)
    assert output == []
    instance._finish_utterance(b"pcm", RATE, local_result())
    assert output == ["джарвис который час"]


def test_unconstrained_wake_verification_rejects_a_forced_grammar_guess():
    instance, output, _ = listener()
    # Command grammar can omit unknown words and suggest a confident wake name.
    # The independent decoder must retain the utterance-start requirement.
    instance._finish_utterance(b"pcm", RATE, local_result(),
                               local_result("это не джарвис который час"))
    assert output == []


def test_negative_utterance_is_never_uploaded_or_replaced_by_positive_grammar():
    calls = []
    instance, output, _ = listener({"recognition_backend": "gemini"},
                                  lambda *args: calls.append(args) or "выключи звук")
    instance._finish_utterance(b"pcm", RATE, local_result("джарвис не выключай звук"))
    assert calls == []
    assert output == []
    instance, output, _ = listener()
    instance._finish_utterance(b"pcm", RATE, local_result("джарвис выключи звук"),
                              local_result("джарвис не выключай звук"))
    assert output == []


def test_cloud_receives_no_ambient_or_uncertain_wake_audio():
    calls = []
    def transcribe(*args):
        calls.append(args)
        return "который час"
    instance, output, _ = listener({"recognition_backend": "gemini"}, transcribe)
    for result in (local_result("фильм идет в фоне"), local_result(confidence=.6),
                   local_result("не джарвис который час")):
        instance._finish_utterance(b"ambient", RATE, result)
    assert calls == []
    assert output == []
    result = local_result("джарвис [unk]")
    result["result"][1]["conf"] = .2
    instance._finish_utterance(b"command", RATE, result)
    assert calls == [(b"command", RATE, "джарвис [unk]")]
    assert output == ["джарвис который час"]


def test_cloud_wake_cannot_be_disabled_by_offline_wake_setting():
    calls = []
    instance, output, _ = listener({"recognition_backend": "gemini", "require_wake_word": False},
                                    lambda *args: calls.append(args) or "который час")
    instance._finish_utterance(b"ambient", RATE, local_result("который час"))
    assert calls == []
    assert output == []
    instance._finish_utterance(b"addressed", RATE, local_result())
    assert len(calls) == 1
    assert output == ["джарвис который час"]


def test_cloud_failure_preserves_confident_offline_commands_without_leaking_error():
    def unavailable(*args):
        raise RuntimeError("secret_api_key_must_not_be_displayed")
    instance, output, states = listener({"recognition_backend": "gemini"}, unavailable)
    instance._finish_utterance(b"pcm", RATE, local_result())
    assert output == ["джарвис который час"]
    assert any("локальное" in state for state in states)
    assert not any("secret" in state for state in states)
    assert not instance.transcribing.is_set()


@pytest.mark.parametrize("event_name", ["speaking", "suspended", "stop_event"])
def test_playback_suspension_or_stop_cannot_emit_or_upload_stale_command(event_name):
    calls = []
    instance, output, _ = listener({"recognition_backend": "gemini"}, lambda *args: calls.append(args))
    getattr(instance, event_name).set()
    instance._finish_utterance(b"stale", RATE, local_result())
    assert calls == []
    assert output == []


def test_offline_mode_never_calls_configured_cloud_callback():
    def forbidden(*args):
        raise AssertionError("offline must not upload audio")
    instance, output, _ = listener({"recognition_backend": "offline"}, forbidden)
    instance._finish_utterance(b"pcm", RATE, local_result())
    assert output == ["джарвис который час"]


def test_stopping_listener_does_not_wait_for_a_slow_cloud_request():
    started, release = threading.Event(), threading.Event()
    def slow_request(*args):
        started.set()
        release.wait(3)
        return "который час"
    instance, output, _ = listener({"recognition_backend": "gemini"}, slow_request)
    worker = threading.Thread(target=instance._finish_utterance,
                              args=(b"pcm", RATE, local_result()))
    worker.start()
    try:
        assert started.wait(1)
        instance.stop()
        worker.join(timeout=.5)
        assert not worker.is_alive()
        assert output == []
        assert not instance.transcribing.is_set()
    finally:
        release.set()
        worker.join(timeout=1)


@pytest.fixture(scope="module")
def real_acoustics():
    pytest.importorskip("webrtcvad")
    from vosk import Model, SetLogLevel
    from jarvis.models import MODEL_NAME
    from jarvis.voice_profiles import voice_assets
    root = Path(__file__).resolve().parents[1]
    model_path = root / "models" / MODEL_NAME
    if not model_path.exists() or not voice_assets():
        pytest.skip("local downloaded speech models are required for acoustic integration")
    SetLogLevel(-1)
    return Model(str(model_path)), root


def gate_recording(samples, rate, gain=1., noise=0.):
    samples = np.interp(np.arange(round(len(samples) * RATE / rate)) * rate / RATE,
                        np.arange(len(samples)), samples) * gain
    samples += np.random.default_rng(51).normal(0, noise, len(samples))
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    return completed(SpeechGate().feed(SILENCE * 30 + pcm + SILENCE * 40))


def decode_recording(model, pcm, grammar=None):
    from vosk import KaldiRecognizer
    recognizer = (KaldiRecognizer(model, RATE, grammar) if grammar is not None
                  else KaldiRecognizer(model, RATE))
    recognizer.SetWords(True)
    recognizer.AcceptWaveform(pcm)
    return json.loads(recognizer.FinalResult())


@pytest.mark.parametrize("text", ["который час", "это не джарвис который час",
                                 "говорили про джарвис который час"])
def test_real_background_speech_never_becomes_an_addressed_command(real_acoustics, tmp_path, text):
    from jarvis.voice_profiles import synthesize
    model, _ = real_acoustics
    samples, rate = synthesize(text, "jarvis", tmp_path / "background.wav")
    recordings = gate_recording(samples, rate)
    assert recordings
    calls = []
    cloud, cloud_output, _ = listener({"recognition_backend": "gemini", "require_wake_word": False},
                                    lambda *args: calls.append(args) or "который час")
    offline, offline_output, _ = listener()
    for pcm in recordings:
        natural = decode_recording(model, pcm)
        constrained = decode_recording(model, pcm, offline._grammar())
        assert not cloud._wake_is_confident(natural)
        cloud._finish_utterance(pcm, RATE, natural, verification_result=constrained)
        offline._finish_utterance(pcm, RATE, constrained, natural)
    assert calls == []
    assert cloud_output == []
    assert offline_output == []


@pytest.mark.parametrize("mode", ["jarvis", "ultron"])
def test_bundled_greeting_speech_does_not_trigger_commands(real_acoustics, mode):
    from jarvis.voice_profiles import read_wav
    model, root = real_acoustics
    samples, rate = read_wav(root / "docs" / "audio" / f"{mode}.wav")
    calls = []
    instance, output, _ = listener({"recognition_backend": "gemini"},
                                  lambda *args: calls.append(args) or "который час")
    recordings = gate_recording(samples, rate)
    assert recordings
    for pcm in recordings:
        result = decode_recording(model, pcm)
        assert not instance._wake_is_confident(result)
        instance._finish_utterance(pcm, RATE, result)
    assert output == []
    assert calls == []


@pytest.mark.parametrize("text", ["Джарвис, не блокируй компьютер",
                                 "Джарвис, не выключай звук", "не открывай блокнот"])
def test_real_negation_cannot_be_dropped_into_an_executable_command(real_acoustics, tmp_path, text):
    from jarvis.voice_profiles import synthesize
    model, _ = real_acoustics
    samples, rate = synthesize(text, "jarvis", tmp_path / "negative.wav")
    recordings = gate_recording(samples, rate)
    assert recordings
    offline, output, _ = listener({"require_wake_word": False})
    calls = []
    cloud, cloud_output, _ = listener({"recognition_backend": "gemini"},
                                     lambda *args: calls.append(args) or "выключи звук")
    for pcm in recordings:
        natural = decode_recording(model, pcm)
        constrained = decode_recording(model, pcm, offline._grammar())
        offline._finish_utterance(pcm, RATE, constrained, natural)
        cloud._finish_utterance(pcm, RATE, natural, verification_result=constrained)
    assert output == []
    assert cloud_output == []
    assert calls == []


@pytest.mark.parametrize("gain", [.10, .04])
def test_quiet_real_command_survives_gate_but_cannot_bypass_cloud_wake(real_acoustics, tmp_path, gain):
    from jarvis.voice_profiles import synthesize
    model, _ = real_acoustics
    samples, rate = synthesize("Джарвис, который час", "jarvis", tmp_path / "quiet.wav")
    recordings = gate_recording(samples, rate, gain, noise=.0005)
    assert len(recordings) == 1
    offline, output, _ = listener({"require_wake_word": False})
    pcm = recordings[0]
    constrained = decode_recording(model, pcm, offline._grammar())
    offline._finish_utterance(pcm, RATE, constrained)
    assert output == ["джарвис который час"]
    calls = []
    cloud, _, _ = listener({"recognition_backend": "gemini"},
                          lambda *args: calls.append(args) or "который час")
    natural = decode_recording(model, pcm)
    cloud._finish_utterance(pcm, RATE, natural)
    # Quiet audio may be heard as a different first word or with low confidence.
    # A grammar's confident guess must never override the natural cloud gate.
    assert bool(calls) == cloud._wake_is_confident(natural)


def test_real_russian_command_survives_gate_and_grammar_with_cloud_confidence_guard(tmp_path):
    pytest.importorskip("webrtcvad")
    from vosk import Model, KaldiRecognizer, SetLogLevel
    from jarvis.models import MODEL_NAME
    from jarvis.voice_profiles import read_wav, synthesize, voice_assets
    root = Path(__file__).resolve().parents[1]
    model_path = root / "models" / MODEL_NAME
    if not model_path.exists() or not voice_assets():
        pytest.skip("local downloaded speech models are required for acoustic integration")
    path = tmp_path / "command.wav"
    synthesize("Джарвис, который час", "jarvis", path)
    samples, rate = read_wav(path)
    samples = np.interp(np.arange(round(len(samples) * RATE / rate)) * rate / RATE,
                        np.arange(len(samples)), samples)
    # Low steady fan noise exercises onset detection and adaptive room floor.
    samples += np.random.default_rng(51).normal(0, .001, len(samples))
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    gate = SpeechGate()
    phrases = completed(gate.feed(SILENCE * 30 + pcm + SILENCE * 40))
    assert len(phrases) == 1
    SetLogLevel(-1)
    model = Model(str(model_path))
    instance, output, _ = listener({"require_wake_word": False})
    recognizer = KaldiRecognizer(model, RATE, instance._grammar())
    recognizer.SetWords(True)
    recognizer.AcceptWaveform(phrases[0])
    result = json.loads(recognizer.FinalResult())
    instance._finish_utterance(phrases[0], RATE, result)
    assert output == ["джарвис который час"]
    # Piper's pronunciation and Vosk confidence vary; recognition of the name
    # must not be assumed. Upload must follow the actual independent result.
    recognizer = KaldiRecognizer(model, RATE)
    recognizer.SetWords(True)
    recognizer.AcceptWaveform(phrases[0])
    natural = json.loads(recognizer.FinalResult())
    calls = []
    cloud, _, _ = listener({"recognition_backend": "gemini"},
                          lambda *args: calls.append(args) or "который час")
    cloud._finish_utterance(phrases[0], RATE, natural)
    assert bool(calls) == cloud._wake_is_confident(natural)
