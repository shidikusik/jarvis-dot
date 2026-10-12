import numpy as np
import pytest

from jarvis.voice_profiles import process_voice, read_wav, write_wav


def test_profiles_lower_pitch_and_remain_bounded():
    rate = 22050
    tone = (.5*np.sin(2*np.pi*220*np.arange(rate)/rate)).astype(np.float32)
    jarvis = process_voice(tone, rate, "jarvis")
    ultron = process_voice(tone, rate, "ultron")
    assert len(ultron) > len(jarvis) > len(tone)
    for output in (jarvis, ultron):
        assert np.isfinite(output).all()
        assert np.max(np.abs(output)) <= .901
    frequency = np.fft.rfftfreq(len(ultron), 1/rate)[np.argmax(np.abs(np.fft.rfft(ultron)))]
    assert 170 < frequency < 180


def test_wav_roundtrip(tmp_path):
    path = tmp_path / "test.wav"
    audio = np.linspace(-.9, .9, 4000, dtype=np.float32)
    write_wav(path, audio, 22050)
    decoded, rate = read_wav(path)
    assert rate == 22050
    assert np.max(np.abs(decoded-audio)) < .0001
