# Third-party components

JARVIS DOT is independent of Luxify, Nothing and Google. Product names describe inspiration or platform support, not affiliation.

- Qt / PySide6 Essentials: LGPLv3 / GPLv3 / commercial (https://doc.qt.io/qtforpython-6/licenses.html). Distributed as dynamically loaded libraries; the portable directory preserves replaceable Qt libraries. Sources and license notices: https://code.qt.io/ and the bundled PySide6 files.
- Vosk API: Apache-2.0 (https://github.com/alphacep/vosk-api).
- `vosk-model-small-ru-0.22`: Apache-2.0, distributed unmodified (https://alphacephei.com/vosk/models).
- python-sounddevice: MIT (https://github.com/spatialaudio/python-sounddevice); PortAudio uses its own permissive license (https://www.portaudio.com/license.html).
- pyttsx3: MPL-2.0 (https://github.com/nateshmbhat/pyttsx3).
- PyInstaller: GPL with bootloader exception (https://pyinstaller.org/en/stable/license.html).
- NumPy: BSD-3-Clause (https://numpy.org/doc/stable/license.html).
- Standalone Piper 2023.11.14-2: MIT legacy engine, executed as a separate process (https://github.com/rhasspy/piper/tree/2023.11.14-2). Unmodified binaries and matching source: https://github.com/rhasspy/piper/releases/tag/2023.11.14-2. Bundled phonemizer includes eSpeak NG (GPLv3); upstream source: https://github.com/espeak-ng/espeak-ng. ONNX Runtime: MIT (https://github.com/microsoft/onnxruntime). Preserve all notices in `models/voice/piper`.
- Russian male `ru_RU-denis-medium` voice: model card / CC0 dataset (https://huggingface.co/rhasspy/piper-voices/tree/main/ru/ru_RU/denis/medium). Model card is included with the voice. The app transforms the model's output; it does not clone any actor.
- Optional local voice conversion: Chatterbox and its model weights (MIT, https://github.com/resemble-ai/chatterbox and https://huggingface.co/ResembleAI/chatterbox); PyTorch (BSD-style, https://github.com/pytorch/pytorch); Resemble Perth watermarking is preserved by the conversion engine (https://github.com/resemble-ai/Perth). Installed separately into `.voice-venv`.
- User-supplied original Jarvis clips: personal imported assets, excluded from the application's MIT license; see `assets/jarvis_pack/README.md`. New converted speech uses these clips as a voice reference. Exact similarity to an actor is not guaranteed.

System speech voices are a fallback provided by the OS or eSpeak. No Luxify assets or proprietary product logos are included. The supplied Jarvis sound pack is explicitly identified as separate personal content.
