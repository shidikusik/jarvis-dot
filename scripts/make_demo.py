"""Render a video of the real Qt app, with captions and local Russian narration."""
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from jarvis.commands import validate_command
from jarvis.storage import Store
from jarvis.ui import MainWindow, CommandEditor
from jarvis.voice_profiles import synthesize, read_wav, write_wav

FPS = 24
WIDTH, HEIGHT = 1920, 1080

SECTIONS = [
    ("intro", 5, "JARVIS DOT", "Нативный помощник. Твой голос. Твой компьютер.", "Джарвис Дот. Независимый голосовой помощник для Виндоус и Линукс."),
    ("home", 8, "НАСТОЯЩЕЕ ПРИЛОЖЕНИЕ", "Qt · локальные команды · никаких аккаунтов", "Это настоящее настольное приложение. Команды и распознавание речи работают на устройстве, без аккаунта и обязательного сервера."),
    ("run", 7, "СКАЗАЛ — ВЫПОЛНИЛ", "Команды голосом, текстом и одним нажатием", "Запускай программы, управляй звуком и выполняй команды. Голос, текст или одна кнопка. Выбирай сам."),
    ("commands", 7, "ТВОИ СЦЕНАРИИ", "Одна фраза запускает несколько действий", "Одна фраза может запустить несколько действий. Добавляй свои команды и собирай сценарии под себя."),
    ("editor", 8, "РЕДАКТОР БЕЗ КОДА", "Отдельные приложения для Windows и Linux", "Редактор работает без кода. Укажи фразы и шаги. Приложения для Виндоус и Линукс настраиваются отдельно."),
    ("ultron", 9, "ULTRON PROTOCOL", "Другой голос. Другой дизайн. Тот же контроль.", "Переключись на Альтрона. Красные акценты, графитовый корпус, точечная маска и низкий металлический голос. Дизайн меняется сразу."),
    ("history", 7, "ВСЁ НА ТВОЁМ ПК", "История и настройки хранятся локально", "История команд и настройки остаются на твоём компьютере. Русские модели уже включены в готовую сборку."),
    ("outro", 5, "JARVIS / ULTRON", "JARVIS DOT · Windows + Linux · Offline", "Джарвис или Альтрон. Твой компьютер. Твои правила."),
]


def font(size, bold=False):
    candidates = [Path("C:/Windows/Fonts/seguisb.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
                  Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
    return ImageFont.truetype(str(next(p for p in candidates if p.exists())), size)


def screenshot(widget):
    image = widget.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    return Image.frombytes("RGBA", (image.width(), image.height()), bytes(image.bits())).convert("RGB")


def main():
    output = ROOT/"dist/JarvisDot-Demo.mp4"
    output.parent.mkdir(exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    voice_dir = ROOT/"build/demo-audio"
    voice_dir.mkdir(parents=True, exist_ok=True)
    soundtrack = []
    for index, (name, seconds, heading, caption, narration) in enumerate(SECTIONS):
        mode = "ultron" if name in {"ultron", "history"} else "jarvis"
        wav = voice_dir/f"{index}.wav"
        if not wav.exists():
            synthesize(narration, mode, wav)
        audio, rate = read_wav(wav)
        target_rate = 24000
        audio = np.interp(np.arange(0, len(audio), rate/target_rate), np.arange(len(audio)), audio).astype(np.float32)
        target = int(seconds*target_rate)
        if len(audio) > target-int(.35*target_rate):
            audio = np.interp(np.linspace(0,len(audio)-1,target-int(.35*target_rate)),np.arange(len(audio)),audio).astype(np.float32)
        section = np.zeros(target, dtype=np.float32)
        start = min(int(.2*target_rate),target-len(audio))
        section[start:start+len(audio)] = audio*.8
        soundtrack.append(section)
        print("Narration:", name, flush=True)
    full_audio = voice_dir/"narration.wav"
    write_wav(full_audio, np.concatenate(soundtrack), 24000)
    silent = ROOT/"build/demo-silent.mp4"
    encoder = subprocess.Popen([ffmpeg,"-y","-loglevel","error","-f","rawvideo","-vcodec","rawvideo","-pix_fmt","rgb24","-s",f"{WIDTH}x{HEIGHT}","-r",str(FPS),"-i","-","-an","-c:v","libx264","-preset","fast","-crf","20","-pix_fmt","yuv420p",str(silent)],stdin=subprocess.PIPE)
    app = QApplication([])
    app.setStyle("Fusion")
    with tempfile.TemporaryDirectory() as temporary:
        window = MainWindow(Store(Path(temporary)), test_mode=True)
        window.resize(1180,780)
        window.show()
        editor = None
        elapsed = 0
        for name, seconds, heading, caption, narration in SECTIONS:
            if name == "home":
                window.navigate(0)
            elif name == "run":
                window.navigate(0)
                window.command_input.setText("который час")
                window.run_text()
            elif name == "commands":
                window.navigate(1)
            elif name == "editor":
                demo = validate_command(dict(title="Режим работы", phrases=["режим работы", "начинаем работу"], actions=[dict(type="open_app", windows="notepad.exe", linux="@text-editor"),dict(type="wait",value="1"),dict(type="speak",value="Все системы готовы, сэр")]))
                editor = CommandEditor(window,demo)
                editor.show()
            elif name == "ultron":
                if editor:
                    editor.close()
                    editor = None
                window.navigate(0)
                window.switch_persona("ultron")
            elif name == "history":
                window.navigate(2)
            for frame in range(seconds*FPS):
                app.processEvents()
                window.dots.phase = (elapsed+frame/FPS)*1.5
                window.dots.update()
                app.processEvents()
                ultron = name in {"ultron", "history"}
                accent = "#ff8176" if ultron else "#d9e7a5"
                canvas = Image.new("RGB",(WIDTH,HEIGHT),"#0d0e12")
                draw = ImageDraw.Draw(canvas)
                if name in {"intro", "outro"}:
                    draw.text((120,160),"INDEPENDENT / OFFLINE / NATIVE",font=font(26),fill=accent)
                    draw.text((112,350),heading,font=font(116,True),fill="#eeefea")
                    draw.text((120,560),caption,font=font(38),fill="#b9beaf")
                    draw.text((120,890),"shidikusik / jarvis-dot",font=font(28),fill=accent)
                    for col in range(14):
                        for row in range(14):
                            bright=abs(math.hypot(col-6.5,row-6.5)-4.8)<.65
                            x,y=1450+col*20,350+row*20
                            draw.ellipse((x,y,x+6,y+6),fill=accent if bright else "#30382a")
                else:
                    draw.text((70,35),heading,font=font(30,True),fill=accent)
                    draw.text((WIDTH-330,40),"JARVIS DOT / 0.1",font=font(22),fill="#b9beaf")
                    shot = screenshot(editor if editor else window)
                    shot.thumbnail((1780,860),Image.Resampling.LANCZOS)
                    x,y=(WIDTH-shot.width)//2,115+(860-shot.height)//2
                    canvas.paste(shot,(x,y))
                    draw.text((70,1000),caption,font=font(30),fill="#e4e9dc")
                encoder.stdin.write(canvas.tobytes())
            elapsed += seconds
            print("Video section:",name,flush=True)
        window.shutdown()
    encoder.stdin.close()
    if encoder.wait():
        raise RuntimeError("Video encoding failed")
    subprocess.run([ffmpeg,"-y","-loglevel","error","-i",str(silent),"-i",str(full_audio),"-c:v","copy","-c:a","aac","-b:a","192k","-shortest","-movflags","+faststart",str(output)],check=True)
    print(output,flush=True)


if __name__ == "__main__":
    main()
