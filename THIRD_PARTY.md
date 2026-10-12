# Third-party components

JARVIS DOT is independent of Luxify, Nothing and Google. Product names describe inspiration or platform support, not affiliation.

- Qt / PySide6 Essentials: LGPLv3 / GPLv3 / commercial (https://doc.qt.io/qtforpython-6/licenses.html). Distributed as dynamically loaded libraries; the portable directory preserves replaceable Qt libraries. Sources and license notices: https://code.qt.io/ and the bundled PySide6 files.
- Vosk API: Apache-2.0 (https://github.com/alphacep/vosk-api).
- `vosk-model-small-ru-0.22`: Apache-2.0, distributed unmodified (https://alphacephei.com/vosk/models).
- python-sounddevice: MIT (https://github.com/spatialaudio/python-sounddevice); PortAudio uses its own permissive license (https://www.portaudio.com/license.html).
- pyttsx3: MPL-2.0 (https://github.com/nateshmbhat/pyttsx3).
- PyInstaller: GPL with bootloader exception (https://pyinstaller.org/en/stable/license.html).
- NumPy: BSD-3-Clause (https://numpy.org/doc/stable/license.html).
- `webrtcvad-wheels` 2.0.14.post1: MIT Python wrapper; bundled WebRTC VAD C code: BSD-3-Clause (https://github.com/daanzu/py-webrtcvad-wheels). The complete notices from the installed wheel are reproduced below and included with portable releases.
- Standalone Piper 2023.11.14-2: MIT legacy engine, executed as a separate process (https://github.com/rhasspy/piper/tree/2023.11.14-2). Unmodified binaries and matching source: https://github.com/rhasspy/piper/releases/tag/2023.11.14-2. Bundled phonemizer includes eSpeak NG (GPLv3); upstream source: https://github.com/espeak-ng/espeak-ng. ONNX Runtime: MIT (https://github.com/microsoft/onnxruntime). Preserve all notices in `models/voice/piper`.
- Russian male `ru_RU-denis-medium` voice: model card / CC0 dataset (https://huggingface.co/rhasspy/piper-voices/tree/main/ru/ru_RU/denis/medium). Model card is included with the voice. The app transforms the model's output; it does not clone any actor.
- Optional local voice conversion: Chatterbox and its model weights (MIT, https://github.com/resemble-ai/chatterbox and https://huggingface.co/ResembleAI/chatterbox); PyTorch (BSD-style, https://github.com/pytorch/pytorch); Resemble Perth watermarking is preserved by the conversion engine (https://github.com/resemble-ai/Perth). Installed separately into `.voice-venv`.
- User-supplied original Jarvis clips: personal imported assets, excluded from the application's MIT license; see `assets/jarvis_pack/README.md`. New converted speech uses these clips as a voice reference. Exact similarity to an actor is not guaranteed.

System speech voices are a fallback provided by the OS or eSpeak. No Luxify assets or proprietary product logos are included. The supplied Jarvis sound pack is explicitly identified as separate personal content.

## WebRTC VAD notices

The following combined license is copied verbatim from `webrtcvad-wheels` 2.0.14.post1, `webrtcvad_wheels-2.0.14.post1.dist-info/licenses/LICENSE`.

```text
The MIT License (MIT)

Copyright (c) 2016 John Wiseman

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

The VAD code under `cbits/webrtc/` is from the WebRTC project, and has
the following license:

============================
Copyright (c) 2011, The WebRTC project authors. All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

  * Redistributions of source code must retain the above copyright
    notice, this list of conditions and the following disclaimer.

  * Redistributions in binary form must reproduce the above copyright
    notice, this list of conditions and the following disclaimer in
    the documentation and/or other materials provided with the
    distribution.

  * Neither the name of Google nor the names of its contributors may
    be used to endorse or promote products derived from this software
    without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```
