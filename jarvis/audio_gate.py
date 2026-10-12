"""Bounded microphone utterances; no recognition or network access in the gate."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math

import numpy as np


@dataclass(frozen=True)
class GateEvent:
    # Only these bytes go to a streaming local recognizer. On start they include
    # the pre-roll so an initial consonant is never cut off by the onset delay.
    audio: bytes = b""
    utterance: bytes | None = None
    started: bool = False
    rejected: bool = False
    level: float = 0.0


class SpeechGate:
    """20 ms VAD, adaptive ambient floor, onset debounce and phrase boundaries.

    ``threshold`` is RMS on a 0..1 PCM scale. The adaptive floor can raise it in
    a noisy room. Short clicks and long continuous noise are never utterances.
    ``vad`` may be injected for tests; production uses WebRTC's local classifier.
    """

    def __init__(self, sample_rate=16000, *, threshold=.004,
                 min_speech_ms=300, silence_ms=680, max_utterance_ms=12000,
                 pre_roll_ms=200, vad=None):
        if sample_rate not in (8000, 16000, 32000, 48000):
            raise ValueError("VAD requires an 8, 16, 32 or 48 kHz sample rate")
        self.sample_rate = sample_rate
        self.frame_ms = 20
        self.frame_bytes = sample_rate * self.frame_ms // 1000 * 2
        frame_samples = self.frame_bytes // 2
        self._window = np.hanning(frame_samples)
        frequencies = np.fft.rfftfreq(frame_samples, 1 / sample_rate)
        self._speech_band = (frequencies >= 180) & (frequencies <= 5000)
        self.threshold = max(.0005, min(.1, float(threshold)))
        self.min_speech_frames = max(1, math.ceil(min_speech_ms / self.frame_ms))
        self.silence_frames = max(1, math.ceil(silence_ms / self.frame_ms))
        self.max_frames = max(self.silence_frames + self.min_speech_frames,
                              math.ceil(max_utterance_ms / self.frame_ms))
        self.pre_roll_frames = max(5, math.ceil(pre_roll_ms / self.frame_ms))
        self._vad = vad
        if self._vad is None:
            import webrtcvad
            self._vad = webrtcvad.Vad(2)
        self.noise_floor = .001
        self.reset()

    @property
    def active(self):
        return bool(self._frames)

    def reset(self):
        """Discard stale audio on playback, suspension, overrun or request end."""
        self._pending = bytearray()
        self._pre_roll = deque(maxlen=self.pre_roll_frames)
        self._recent = deque(maxlen=5)
        self._ambient = deque(maxlen=100)
        self._frames = []
        self._voiced = 0
        self._silent = 0
        self._blocked_until_silence = False

    def _voice(self, frame):
        samples = np.frombuffer(frame, dtype="<i2").astype(np.float32) / 32768
        # Centering removes DC from inexpensive USB microphones without changing
        # the original recording that is later sent to Vosk or the transcriber.
        centered = samples - samples.mean()
        rms = float(np.sqrt(np.mean(centered * centered)))
        power = np.abs(np.fft.rfft(centered * self._window)) ** 2
        total_power = float(power.sum())
        fraction = float(power[self._speech_band].sum()) / total_power if total_power else 0.
        band_rms = rms * math.sqrt(fraction)
        classified = bool(self._vad.is_speech(frame, self.sample_rate))
        threshold = max(self.threshold, self.noise_floor * 2.5)
        # WebRTC can label sustained 50/60 Hz microphone hum as voiced. Require
        # some speech-band energy and measure the floor in that same band, so a
        # loud low-frequency fan does not suppress otherwise audible consonants.
        voice = classified and fraction >= .025 and band_rms >= threshold
        if not self.active and (not classified or fraction < .025):
            self._ambient.append(band_rms)
            if self._ambient:
                estimate = float(np.percentile(self._ambient, 70))
                self.noise_floor = max(.0002, .90 * self.noise_floor + .10 * estimate)
        return voice, min(1., rms * 9)

    def feed(self, data: bytes) -> list[GateEvent]:
        """Accept arbitrary callback chunks and return frame/utterance events."""
        self._pending.extend(data)
        events = []
        while len(self._pending) >= self.frame_bytes:
            frame = bytes(self._pending[:self.frame_bytes])
            del self._pending[:self.frame_bytes]
            voice, level = self._voice(frame)
            if self._blocked_until_silence:
                self._silent = 0 if voice else self._silent + 1
                if self._silent >= self.silence_frames:
                    self._blocked_until_silence = False
                    self._silent = 0
                events.append(GateEvent(level=level))
                continue
            if not self.active:
                self._pre_roll.append((frame, voice))
                self._recent.append(voice)
                # Three speech frames in a five-frame window prevents a click
                # from becoming a capture while allowing unvoiced consonants.
                if sum(self._recent) < 3:
                    events.append(GateEvent(level=level))
                    continue
                self._frames = [item[0] for item in self._pre_roll]
                self._voiced = sum(item[1] for item in self._pre_roll)
                self._silent = 0
                self._pre_roll.clear()
                self._recent.clear()
                events.append(GateEvent(audio=b"".join(self._frames), started=True, level=level))
                continue
            self._frames.append(frame)
            self._voiced += int(voice)
            self._silent = 0 if voice else self._silent + 1
            if len(self._frames) >= self.max_frames:
                # Never execute the truncated beginning of a longer sentence.
                self._frames = []
                self._voiced = 0
                self._silent = 0
                self._blocked_until_silence = True
                events.append(GateEvent(rejected=True, level=level))
            elif self._silent >= self.silence_frames:
                valid = self._voiced >= self.min_speech_frames
                # Retain 160 ms of ending context; discard the remaining tail.
                tail = max(0, self._silent - 8)
                utterance = b"".join(self._frames[:-tail] if tail else self._frames) if valid else None
                self._frames = []
                self._voiced = 0
                self._silent = 0
                events.append(GateEvent(audio=frame, utterance=utterance,
                                        rejected=not valid, level=level))
            else:
                events.append(GateEvent(audio=frame, level=level))
        return events
