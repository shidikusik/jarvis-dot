from __future__ import annotations

from datetime import datetime
import json
import math
from pathlib import Path
import sys

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMenu, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QSpinBox, QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from jarvis import __version__
from jarvis.cloud import GeminiCommandRecognizer
from jarvis.commands import defaults, match_phrase, validate_collection, validate_command
from jarvis.credentials import (CredentialsError, delete_gemini_key,
    has_gemini_key, load_gemini_key, save_gemini_key)
from jarvis.models import find_model
from jarvis.platform_actions import Executor
from jarvis.storage import Store
from jarvis.voice import Listener, Speaker
from jarvis.workers import ModelWorker, RunWorker


def label(text, name="", wrap=False):
    result = QLabel(text)
    result.setObjectName(name)
    result.setWordWrap(wrap)
    return result


def button(text, callback, name=""):
    result = QPushButton(text)
    result.setObjectName(name)
    result.setCursor(Qt.CursorShape.PointingHandCursor)
    result.clicked.connect(callback)
    return result


def panel(name="card"):
    result = QFrame()
    result.setObjectName(name)
    return result


def scroll(content):
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setWidget(content)
    return area


class DotField(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(260, 150)
        self.accent = QColor("#d9e7a5")
        self.persona = "jarvis"
        self.listening, self.level, self.phase = False, 0., 0.
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(70)

    def tick(self):
        self.phase += .13
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pitch = min(self.width()/22, self.height()/19)
        cx, cy = self.width()/2, self.height()/2
        for row in range(-8, 9):
            for col in range(-9, 10):
                distance = math.hypot(col, row)
                angle = math.atan2(row, col)
                ring = abs(distance - (5.9 + (.45 * math.sin(self.phase + angle*3) if self.listening else 0)))
                if self.persona == "ultron":
                    eye = (row in (-2, -1) and 2 <= abs(col) <= 6 and (row != -2 or abs(col) <= 5))
                    outline = (abs(col) == 7 and -4 <= row <= 1) or (row == -6 and abs(col) <= 4) or (row == -5 and abs(col) in (5, 6))
                    jaw = 2 <= row <= 6 and abs(col) == 7-row
                    mouth = row == 3 and abs(col) <= 2
                    bright = eye or outline or jaw or mouth
                else:
                    bright = ring < .85 or (self.listening and abs(col) < 4 and abs(row) < 1 + self.level*5)
                color = QColor(self.accent if bright else ("#302327" if self.persona == "ultron" else "#383a36"))
                if bright:
                    color.setAlphaF(.55 + .45 * (math.sin(self.phase + distance*.3)**2))
                painter.setBrush(color)
                painter.setPen(Qt.PenStyle.NoPen)
                size = 2.6 if bright else 1.6
                painter.drawEllipse(int(cx + col*pitch-size), int(cy + row*pitch-size), int(size*2), int(size*2))


ACTION_LABELS = {
    "open_app": "Открыть приложение", "open_folder": "Открыть папку", "open_url": "Открыть сайт",
    "media": "Звук / музыка", "wait": "Пауза (секунды)", "speak": "Произнести текст",
    "time": "Назвать время", "note": "Сохранить заметку", "lock": "Заблокировать ПК",
}


class ActionRow(QFrame):
    def __init__(self, action, remove):
        super().__init__()
        self.setObjectName("actionRow")
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.kind = QComboBox()
        for key, title in ACTION_LABELS.items():
            self.kind.addItem(title, key)
        self.kind.setCurrentIndex(self.kind.findData(action.get("type", "speak")))
        header.addWidget(self.kind, 1)
        header.addWidget(button("×", lambda: remove(self), "smallButton"))
        layout.addLayout(header)
        self.fields = QStackedWidget()
        self.value = QLineEdit(action.get("value", ""))
        self.value.setPlaceholderText("Текст, путь, URL или число секунд")
        self.fields.addWidget(self.value)
        apps = QWidget()
        form = QFormLayout(apps)
        form.setContentsMargins(0, 0, 0, 0)
        self.windows = QLineEdit(action.get("windows", ""))
        self.windows.setPlaceholderText('notepad.exe или "C:\\Program Files\\App\\app.exe"')
        self.linux = QLineEdit(action.get("linux", ""))
        self.linux.setPlaceholderText("kate или @text-editor")
        form.addRow("Windows", self.windows)
        form.addRow("Linux", self.linux)
        self.fields.addWidget(apps)
        self.media = QComboBox()
        for title, value in [("Громче", "volume_up"), ("Тише", "volume_down"), ("Звук вкл / выкл", "mute"), ("Пауза / продолжить", "play_pause"), ("Следующий трек", "next"), ("Предыдущий трек", "previous")]:
            self.media.addItem(title, value)
        index = self.media.findData(action.get("value"))
        self.media.setCurrentIndex(max(0, index))
        self.fields.addWidget(self.media)
        self.fields.addWidget(label("Подтверждение блокировки обязательно.", "muted", True))
        self.fields.addWidget(label("Помощник назовёт текущее время.", "muted", True))
        layout.addWidget(self.fields)
        self.kind.currentIndexChanged.connect(self.sync)
        self.sync()

    def sync(self):
        self.fields.setCurrentIndex({"open_app": 1, "media": 2, "lock": 3, "time": 4}.get(self.kind.currentData(), 0))

    def action(self):
        kind = self.kind.currentData()
        if kind == "open_app":
            return dict(type=kind, windows=self.windows.text(), linux=self.linux.text())
        if kind == "media":
            return dict(type=kind, value=self.media.currentData())
        return dict(type=kind, value=self.value.text())


class CommandEditor(QDialog):
    def __init__(self, parent, command=None):
        super().__init__(parent)
        self.setWindowTitle("Редактор команды · JARVIS DOT")
        self.resize(680, 730)
        self.original = command or {}
        self.result_command = None
        self.rows = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addWidget(label("СОБЕРИ СВОЙ СЦЕНАРИЙ", "eyebrow"))
        layout.addWidget(label("Одна фраза. Твои действия.", "sectionTitle"))
        self.title = QLineEdit(self.original.get("title", ""))
        self.title.setPlaceholderText("Название команды")
        layout.addWidget(self.title)
        self.phrases = QPlainTextEdit("\n".join(self.original.get("phrases", [])))
        self.phrases.setPlaceholderText("Фразы без слова «Джарвис» — каждая с новой строки")
        self.phrases.setMaximumHeight(95)
        layout.addWidget(self.phrases)
        content = QWidget()
        self.actions_layout = QVBoxLayout(content)
        self.actions_layout.setContentsMargins(0, 0, 0, 0)
        self.actions_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(scroll(content), 1)
        for action in self.original.get("actions", [{"type": "speak", "value": "Готово"}]):
            self.add_action(action)
        layout.addWidget(button("+ Добавить действие", lambda: self.add_action({"type": "speak"})))
        self.confirm = QCheckBox("Спрашивать подтверждение перед выполнением")
        self.confirm.setChecked(self.original.get("confirm", False))
        layout.addWidget(self.confirm)
        self.enabled = QCheckBox("Команда включена")
        self.enabled.setChecked(self.original.get("enabled", True))
        layout.addWidget(self.enabled)
        row = QHBoxLayout()
        row.addWidget(button("Отмена", self.reject))
        row.addWidget(button("Сохранить команду", self.save, "primary"))
        layout.addLayout(row)

    def add_action(self, action):
        if len(self.rows) >= 40:
            return
        row = ActionRow(action, self.remove)
        self.rows.append(row)
        self.actions_layout.addWidget(row)

    def remove(self, row):
        self.rows.remove(row)
        self.actions_layout.removeWidget(row)
        row.deleteLater()

    def save(self):
        try:
            self.result_command = validate_command(dict(
                id=self.original.get("id"), title=self.title.text(),
                phrases=[p for p in self.phrases.toPlainText().splitlines() if p.strip()],
                actions=[row.action() for row in self.rows],
                enabled=self.enabled.isChecked(), confirm=self.confirm.isChecked()))
        except ValueError as exc:
            QMessageBox.warning(self, "Проверьте команду", str(exc))
            return
        self.accept()


class MainWindow(QMainWindow):
    speech_error = Signal(str)
    speech_state = Signal(str)

    def __init__(self, store=None, test_mode=False):
        super().__init__()
        self.store = store or Store()
        self.settings = self.store.settings()
        self._offline_require_wake = self.settings["require_wake_word"]
        self.commands = validate_collection(self.store.read("commands.json", defaults()))
        self.test_mode = test_mode
        self.listener = self.runner = self.downloader = None
        self._cloud_recognizer = None
        self._quitting = False
        self.pending_phrase = ""
        self.speaker = Speaker(self.speech_error.emit, self.speech_state.emit)
        self.speaker.enabled = self.settings["spoken_replies"] and not test_mode
        self.speaker.mode = self.settings["voice_mode"]
        self.configure_speaker()
        self.executor = Executor(self.store.root, self.speaker.say)
        self.setWindowTitle("JARVIS DOT · Desktop assistant")
        self.resize(1180, 820)
        self.setMinimumSize(980, 720)
        self.make_icon()
        self.setWindowIcon(self.app_icon)
        self.make_ui()
        self.apply_theme()
        self.setup_tray()
        self.speech_error.connect(lambda message: self.status_label.setText(message))
        self.speech_state.connect(self.status_label.setText)
        self.refresh_commands()
        self.refresh_history()
        self.refresh_model()
        self.refresh_recognition_status()

    def make_icon(self):
        pixmap = QPixmap(64, 64)
        pixmap.fill(QColor("#171816"))
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#d9e7a5"))
        for x in range(-3, 4):
            for y in range(-3, 4):
                if 2 < math.hypot(x, y) < 3.5:
                    p.drawEllipse(30+x*7, 30+y*7, 4, 4)
        p.end()
        self.app_icon = QIcon(pixmap)

    def make_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        sidebar = panel("sidebar")
        sidebar.setFixedWidth(210)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(24, 34, 20, 26)
        self.brand = label("JARVIS", "brand")
        side.addWidget(self.brand)
        side.addWidget(label("D O T  /  0 2", "eyebrow"))
        side.addSpacing(40)
        self.nav = []
        for i, text in enumerate(["◉   Ассистент", "▦   Команды", "≡   История", "⚙   Настройки"]):
            b = button(text, lambda checked=False, index=i: self.navigate(index), "nav")
            b.setCheckable(True)
            self.nav.append(b)
            side.addWidget(b)
        side.addStretch()
        side.addWidget(label("●  LOCAL FIRST", "online"))
        side.addWidget(label("Твой голос.\nТвой компьютер.\nТвои правила.", "muted", True))
        side.addSpacing(18)
        side.addWidget(label(f"WINDOWS + LINUX\nv{__version__} · независимый", "tiny"))
        shell.addWidget(sidebar)
        container = QWidget()
        main = QVBoxLayout(container)
        main.setContentsMargins(32, 28, 32, 20)
        main.setSpacing(18)
        header = QHBoxLayout()
        self.page_title = label("Ассистент", "sectionTitle")
        header.addWidget(self.page_title)
        header.addStretch()
        self.persona_switch = QComboBox()
        self.persona_switch.addItem("◉  JARVIS", "jarvis")
        self.persona_switch.addItem("◈  ULTRON", "ultron")
        self.persona_switch.setCurrentIndex(max(0, self.persona_switch.findData(self.settings["voice_mode"])))
        self.persona_switch.currentIndexChanged.connect(lambda: self.switch_persona(self.persona_switch.currentData()))
        header.addWidget(self.persona_switch)
        self.recognition_chip = label("●  ОФЛАЙН", "chip")
        header.addWidget(self.recognition_chip)
        main.addLayout(header)
        self.pages = QStackedWidget()
        main.addWidget(self.pages, 1)
        self.home_page()
        self.commands_page()
        self.history_page()
        self.settings_page()
        self.status_label = label("Готов. Микрофон включается только по вашей кнопке.", "tiny", True)
        main.addWidget(self.status_label)
        shell.addWidget(container, 1)
        self.navigate(0)

    def home_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.hero_eyebrow = label("МЕНЬШЕ КЛИКОВ. БОЛЬШЕ ДЕЙСТВИЙ.", "eyebrow")
        layout.addWidget(self.hero_eyebrow)
        self.hero_title = label("Твой ПК.\nПод твоим голосом.", "heroTitle")
        layout.addWidget(self.hero_title)
        self.recognition_description = label("Распознавание и команды выполняются на этом устройстве.", "muted", True)
        layout.addWidget(self.recognition_description)
        row = QHBoxLayout()
        row.setSpacing(18)
        hero = panel("heroCard")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(24, 12, 24, 24)
        badge = QHBoxLayout()
        badge.addWidget(label("VOICE ENGINE", "eyebrow"))
        badge.addStretch()
        self.voice_badge = label("ОЖИДАНИЕ", "tiny")
        badge.addWidget(self.voice_badge)
        hero_layout.addLayout(badge)
        self.dots = DotField()
        hero_layout.addWidget(self.dots, 1)
        self.voice_text = label("«Джарвис, который час?»", "voiceText", True)
        self.voice_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero_layout.addWidget(self.voice_text)
        self.listen_button = button("●  Включить микрофон", self.toggle_listening, "primary")
        hero_layout.addWidget(self.listen_button)
        row.addWidget(hero, 3)
        quick = panel()
        quick_layout = QVBoxLayout(quick)
        quick_layout.setContentsMargins(22, 24, 22, 24)
        quick_layout.addWidget(label("БЫСТРЫЙ ЗАПУСК", "eyebrow"))
        quick_layout.addWidget(label("Нажми. Или скажи.", "cardTitle"))
        quick_layout.addSpacing(12)
        for key, title in [("time", "◷   Который час"), ("files", "▤   Открыть файлы"), ("notes", "✎   Блокнот"), ("work", "↗   Режим работы")]:
            quick_layout.addWidget(button(title, lambda checked=False, k=key: self.run_by_id(k), "quick"))
        quick_layout.addStretch()
        self.count_label = label("", "tiny")
        quick_layout.addWidget(self.count_label)
        row.addWidget(quick, 2)
        layout.addLayout(row, 1)
        input_panel = panel()
        input_layout = QVBoxLayout(input_panel)
        input_layout.setContentsMargins(20, 16, 20, 16)
        input_layout.addWidget(label("КОМАНДА ТЕКСТОМ", "eyebrow"))
        input_row = QHBoxLayout()
        self.command_input = QLineEdit()
        self.command_input.setPlaceholderText("открой файлы и затем который час")
        self.command_input.returnPressed.connect(self.run_text)
        input_row.addWidget(self.command_input, 1)
        input_row.addWidget(button("Выполнить ↗", self.run_text, "primary"))
        input_layout.addLayout(input_row)
        self.stop_button = button("■  Остановить сценарий", self.cancel_run)
        self.stop_button.setVisible(False)
        input_layout.addWidget(self.stop_button)
        self.response = label("Введите команду или включите микрофон.", "muted", True)
        input_layout.addWidget(self.response)
        layout.addWidget(input_panel)
        self.pages.addWidget(page)

    def commands_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label("Слова превращаются в действия.", "heroSmall"))
        layout.addWidget(label("Свои фразы, отдельные приложения для каждой ОС, цепочки шагов.", "muted", True))
        row = QHBoxLayout()
        row.addWidget(button("+ Новая команда", lambda: self.edit_command(), "primary"))
        row.addStretch()
        row.addWidget(button("Импорт", self.import_commands))
        row.addWidget(button("Экспорт", self.export_commands))
        layout.addLayout(row)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Найти команду или фразу…")
        self.search.textChanged.connect(self.refresh_commands)
        layout.addWidget(self.search)
        self.command_cards = QWidget()
        self.command_grid = QGridLayout(self.command_cards)
        self.command_grid.setContentsMargins(0, 8, 0, 8)
        self.command_grid.setSpacing(12)
        self.command_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(scroll(self.command_cards), 1)
        self.pages.addWidget(page)

    def history_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(label("Что произошло на твоём ПК.", "heroSmall"))
        row.addStretch()
        row.addWidget(button("Очистить", self.clear_history))
        layout.addLayout(row)
        layout.addWidget(label("Последние 100 запусков. Хранятся только на устройстве.", "muted"))
        content = QWidget()
        self.history_layout = QVBoxLayout(content)
        self.history_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.history_layout.setContentsMargins(0, 10, 0, 0)
        layout.addWidget(scroll(content), 1)
        self.pages.addWidget(page)

    def settings_page(self):
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(16)
        layout.addWidget(label("Настроено под тебя.", "heroSmall"))
        recognition = panel()
        rf = QFormLayout(recognition)
        rf.setContentsMargins(24, 24, 24, 24)
        rf.addRow(label("РАСПОЗНАВАНИЕ КОМАНД", "eyebrow"))
        self.recognition_backend = QComboBox()
        self.recognition_backend.addItem("Офлайн · на этом компьютере", "offline")
        self.recognition_backend.addItem("Google Gemini · лучше понимает речь", "gemini")
        self.recognition_backend.setCurrentIndex(max(0, self.recognition_backend.findData(self.settings.get("recognition_backend", "offline"))))
        rf.addRow("Режим распознавания", self.recognition_backend)
        self.gemini_key = QLineEdit()
        self.gemini_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.gemini_key.setPlaceholderText("Вставьте свой ключ из Google AI Studio")
        rf.addRow("API-ключ Google", self.gemini_key)
        key_buttons = QHBoxLayout()
        self.save_key_button = button("Сохранить ключ", self.save_cloud_key)
        self.forget_key_button = button("Удалить ключ", self.forget_cloud_key)
        key_buttons.addWidget(self.save_key_button)
        key_buttons.addWidget(self.forget_key_button)
        rf.addRow(key_buttons)
        self.key_status = label("Ключ не сохранён.", "tiny", True)
        rf.addRow(self.key_status)
        self.recognition_note = label("", "muted", True)
        rf.addRow(self.recognition_note)
        rf.addRow(label("Google получает короткую команду после распознанного имени, до 12 секунд, и список названий/фраз команд. Бесплатный тариф имеет квоты; Google может использовать отправленное содержимое для улучшения продуктов. Полностью локальная работа доступна в офлайн-режиме.", "tiny", True))
        self.speech_threshold = QDoubleSpinBox()
        self.speech_threshold.setRange(.0005, .1)
        self.speech_threshold.setDecimals(4)
        self.speech_threshold.setSingleStep(.001)
        self.speech_threshold.setValue(float(self.settings.get("speech_threshold", .004)))
        self.speech_threshold.setToolTip("Больше значение — сильнее отсеиваются тихие фоновые звуки. Меньше — легче услышать тихую речь.")
        rf.addRow("Порог громкости микрофона", self.speech_threshold)
        self.recognition_confidence = QSpinBox()
        self.recognition_confidence.setRange(50, 99)
        self.recognition_confidence.setSuffix(" %")
        self.recognition_confidence.setValue(round(float(self.settings.get("min_recognition_confidence", .72)) * 100))
        self.recognition_confidence.setToolTip("Минимальная уверенность локального распознавания. Выше — меньше случайных команд, но чаще нужно повторять.")
        rf.addRow("Уверенность распознавания", self.recognition_confidence)
        rf.addRow(label("Если мешает фон, увеличьте порог шума. Если тихий голос пропускается, немного уменьшите. Во время ответа помощник не слушает себя.", "tiny", True))
        layout.addWidget(recognition)
        voice = panel()
        form = QFormLayout(voice)
        form.setContentsMargins(24, 24, 24, 24)
        form.addRow(label("ГОЛОС И МИКРОФОН", "eyebrow"))
        self.wake = QLineEdit(self.settings["wake_word"])
        form.addRow("Имя помощника", self.wake)
        self.require_wake = QCheckBox("Слушать команды только после имени")
        self.require_wake.setChecked(self.settings["require_wake_word"])
        form.addRow(self.require_wake)
        self.spoken = QCheckBox("Озвучивать ответы выбранным голосом")
        self.spoken.setChecked(self.settings["spoken_replies"])
        form.addRow(self.spoken)
        from jarvis.voice_profiles import VOICE_MODES, voice_assets
        self.voice_modes = QComboBox()
        for key, profile in VOICE_MODES.items():
            self.voice_modes.addItem(profile["title"], key)
        self.voice_modes.setCurrentIndex(max(0, self.voice_modes.findData(self.settings["voice_mode"])))
        form.addRow("Голос и оформление", self.voice_modes)
        self.voice_modes.currentIndexChanged.connect(lambda: self.switch_persona(self.voice_modes.currentData()))
        form.addRow(button("Послушать выбранный голос", self.preview_voice))
        form.addRow(label("Мужской нейроголос + обработка. " + ("Нейромодель установлена." if voice_assets() else "Пока доступен только системный голос. Установите нейромодель из README."), "tiny", True))
        self.use_pack = QCheckBox("Оригинальные короткие ответы из твоего пака")
        self.use_pack.setChecked(self.settings["use_voice_pack"])
        form.addRow(self.use_pack)
        form.addRow(button("Послушать оригинальную запись", self.preview_recording))
        self.microphones = QComboBox()
        self.microphones.addItem("Системный микрофон", None)
        try:
            import sounddevice as sd
            for index, device in enumerate(sd.query_devices()):
                if device["max_input_channels"] > 0:
                    self.microphones.addItem(f"{index}: {device['name']}", index)
        except Exception:
            pass
        self.microphones.setCurrentIndex(max(0, self.microphones.findData(self.settings["microphone"])))
        form.addRow("Устройство ввода", self.microphones)
        layout.addWidget(voice)
        clone = panel()
        cf = QFormLayout(clone)
        cf.setContentsMargins(24, 24, 24, 24)
        cf.addRow(label("ПЕРЕНОС ГОЛОСА ИЗ ПАКА · ЛОКАЛЬНО", "eyebrow"))
        self.clone_enabled = QCheckBox("Синтезировать новые фразы с тембром из пака")
        self.clone_enabled.setChecked(self.settings["clone_enabled"])
        cf.addRow(self.clone_enabled)
        self.clone_python = QLineEdit(self.settings["clone_python"])
        self.clone_python.setPlaceholderText(".voice-venv/Scripts/python.exe или .voice-venv/bin/python")
        cf.addRow("Python движка", self.clone_python)
        self.clone_model = QLineEdit(self.settings["clone_model"])
        self.clone_model.setPlaceholderText("Папка с s3gen.safetensors")
        cf.addRow("Модель переноса", self.clone_model)
        cf.addRow(label("Дополнительный движок требует отдельной установки. Первый новый ответ медленнее обычного; ответы кешируются. Все вычисления и образец остаются на ПК.", "tiny", True))
        layout.addWidget(clone)
        model = panel()
        ml = QVBoxLayout(model)
        ml.setContentsMargins(24, 24, 24, 24)
        ml.addWidget(label("ЛОКАЛЬНАЯ МОДЕЛЬ · РУССКИЙ", "eyebrow"))
        self.model_status = label("", "muted", True)
        ml.addWidget(self.model_status)
        self.model_path = QLineEdit(self.settings["model_path"])
        self.model_path.setPlaceholderText("Автоматически: встроенная модель или папка данных")
        ml.addWidget(self.model_path)
        row = QHBoxLayout()
        row.addWidget(button("Выбрать папку", self.choose_model))
        self.download_button = button("Скачать модель · 45 МБ", self.download_model)
        row.addWidget(self.download_button)
        ml.addLayout(row)
        ml.addWidget(label("Модель нужна для офлайн-команд и проверки имени перед отправкой команды в Google. Можно перенести её с другого ПК. В готовых сборках модель уже есть.", "tiny", True))
        layout.addWidget(model)
        look = panel()
        form = QFormLayout(look)
        form.setContentsMargins(24, 24, 24, 24)
        form.addRow(label("ВНЕШНИЙ ВИД И ПОВЕДЕНИЕ", "eyebrow"))
        self.accents = QComboBox()
        for title, color in [("Sage · шалфей", "#d9e7a5"), ("Ice · лёд", "#b9dff3"), ("Lilac · сирень", "#ddc7fa"), ("Nothing · красный", "#ffb4aa")]:
            self.accents.addItem(title, color)
        self.accents.setCurrentIndex(max(0, self.accents.findData(self.settings["accent"])))
        form.addRow("Цветовой акцент", self.accents)
        self.close_to_tray = QCheckBox("При закрытии сворачивать в трей")
        self.close_to_tray.setChecked(self.settings["close_to_tray"])
        form.addRow(self.close_to_tray)
        layout.addWidget(look)
        layout.addWidget(button("Сохранить настройки", self.save_settings, "primary"))
        layout.addWidget(button("Открыть папку данных", lambda: self.executor.execute([validate_command(dict(title="Папка данных", phrases=["данные"], actions=[dict(type="open_folder", value=str(self.store.root))]))], __import__("threading").Event())))
        layout.addWidget(label("Офлайн-режим работает без аккаунта и ключа. Google подключается по вашему выбору.\nМикрофон выключен при старте. Приложение не сохраняет записи звука; ключ хранится отдельно от настроек.", "muted", True))
        layout.addStretch()
        self.pages.addWidget(scroll(content))
        self.recognition_backend.currentIndexChanged.connect(self.update_recognition_controls)
        self.update_recognition_controls()

    def update_recognition_controls(self):
        online = self.recognition_backend.currentData() == "gemini"
        self.gemini_key.setEnabled(online)
        self.save_key_button.setEnabled(online)
        self.forget_key_button.setEnabled(online)
        if online:
            if self.require_wake.isEnabled():
                self._offline_require_wake = self.require_wake.isChecked()
            self.require_wake.setChecked(True)
        elif not self.require_wake.isEnabled():
            self.require_wake.setChecked(self._offline_require_wake)
        self.require_wake.setEnabled(not online)
        self.require_wake.setText("Google всегда слушает команды только после имени" if online else "Слушать команды только после имени")
        self.recognition_note.setText(
            "Короткие голосовые команды распознаёт Gemini; действия выполняются на ПК. Имя помощника обязательно. Для применения нажмите «Сохранить настройки»."
            if online else "Распознавание работает на ПК без интернета. Для применения нажмите «Сохранить настройки».")

    def refresh_recognition_status(self):
        configured = has_gemini_key()
        self.key_status.setText("Ключ сохранён в папке данных пользователя." if configured else "Ключ не сохранён. Получите бесплатный ключ в Google AI Studio.")
        if self.settings.get("recognition_backend", "offline") == "gemini":
            self.recognition_chip.setText("●  GOOGLE" if configured else "●  НУЖЕН КЛЮЧ")
            self.recognition_description.setText("Google распознаёт короткие команды после имени помощника. Действия выполняются на этом компьютере.")
        else:
            self.recognition_chip.setText("●  ОФЛАЙН")
            self.recognition_description.setText("Распознавание и команды выполняются на этом устройстве.")

    def save_cloud_key(self):
        if self.listener and self.listener.isRunning():
            self.status_label.setText("Выключите микрофон перед изменением ключа.")
            return
        try:
            save_gemini_key(self.gemini_key.text())
        except CredentialsError as exc:
            self.status_label.setText(str(exc))
            return
        self.gemini_key.clear()
        self.refresh_recognition_status()
        self.status_label.setText("Ключ сохранён. Google готов к распознаванию." if self.settings.get("recognition_backend") == "gemini" else "Ключ сохранён. Выберите Google и сохраните настройки, чтобы включить его.")

    def forget_cloud_key(self):
        if self.listener and self.listener.isRunning():
            self.status_label.setText("Выключите микрофон перед удалением ключа.")
            return
        try:
            delete_gemini_key()
        except CredentialsError as exc:
            self.status_label.setText(str(exc))
            return
        self.gemini_key.clear()
        self.refresh_recognition_status()
        self.status_label.setText("Ключ удалён. Офлайн-режим доступен без ключа.")

    def apply_theme(self):
        accent = self.settings["accent"]
        if accent not in {"#d9e7a5", "#b9dff3", "#ddc7fa", "#ffb4aa"}:
            accent = "#d9e7a5"
        self.dots.accent = QColor(accent)
        self.setStyleSheet(f"""
            QWidget {{ background: #111310; color: #eeefea; font-family: 'Segoe UI', 'Noto Sans', sans-serif; font-size: 14px; }}
            QLabel {{ background: transparent; }}
            #sidebar {{ background: #191b17; border-right: 1px solid #2a2d26; }}
            #brand {{ font-family: 'Consolas', 'DejaVu Sans Mono'; font-size: 32px; font-weight: 700; letter-spacing: 4px; }}
            #eyebrow {{ color: #b8bcb0; font-size: 11px; font-weight: 600; letter-spacing: 2px; background: transparent; }}
            #sectionTitle {{ font-size: 25px; font-weight: 600; }}
            #heroTitle {{ font-size: 36px; font-weight: 600; letter-spacing: -1px; }}
            #heroSmall {{ font-size: 28px; font-weight: 600; }}
            #cardTitle {{ font-size: 20px; font-weight: 600; background: transparent; }}
            #muted {{ color: #adb2a5; font-size: 13px; background: transparent; }}
            #tiny {{ color: #919889; font-size: 11px; background: transparent; }}
            #online {{ color: {accent}; font-family: 'Consolas', 'DejaVu Sans Mono'; font-size: 12px; }}
            #chip {{ background: #292f20; color: {accent}; padding: 9px 15px; border-radius: 15px; font-size: 11px; font-weight: 700; }}
            #card, #heroCard {{ background: #1d211a; border: 1px solid #2b3026; border-radius: 24px; }}
            #heroCard {{ background: #181c16; }}
            #card QLabel, #heroCard QLabel, #heroCard QWidget {{ background: transparent; }}
            #voiceText {{ font-size: 17px; font-weight: 500; padding: 8px; }}
            QPushButton {{ background: #2c3226; color: #e2e7d9; border: none; border-radius: 17px; padding: 10px 18px; min-height: 20px; font-weight: 500; }}
            QPushButton:hover {{ background: #3b4432; }}
            QPushButton:pressed {{ background: #4d583f; }}
            QPushButton:disabled {{ color: #747b6c; background: #272b22; }}
            QPushButton#primary {{ background: {accent}; color: #202817; font-weight: 700; }}
            QPushButton#primary:hover {{ background: #eef6d7; }}
            QPushButton#nav {{ text-align: left; background: transparent; padding: 15px 12px; color: #a5ad9c; }}
            QPushButton#nav:checked {{ background: #303925; color: {accent}; }}
            QPushButton#quick {{ text-align: left; padding: 12px; background: #293022; }}
            QPushButton#smallButton {{ padding: 5px 12px; border-radius: 12px; min-height: 16px; }}
            QLineEdit, QPlainTextEdit, QComboBox, QDoubleSpinBox, QSpinBox {{ background: #131710; border: 1px solid #414937; border-radius: 12px; padding: 11px; selection-background-color: #515d3e; }}
            QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus {{ border: 1px solid {accent}; }}
            QComboBox QAbstractItemView {{ background: #242b1e; selection-background-color: #455234; }}
            QCheckBox {{ background: transparent; spacing: 12px; padding: 5px 0; }}
            QCheckBox::indicator {{ width: 20px; height: 20px; border: 1px solid #5c674d; border-radius: 6px; background: #171c12; }}
            QCheckBox::indicator:checked {{ background: {accent}; }}
            QScrollBar:vertical {{ background: transparent; width: 7px; margin: 2px; }}
            QScrollBar::handle:vertical {{ background: #46503b; border-radius: 3px; min-height: 24px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            #actionRow {{ background: #242b1e; border-radius: 14px; }}
            QToolTip {{ background: #2e3725; color: #eef3e4; border: none; padding: 8px; }}
        """)
        mode = self.settings.get("voice_mode", "jarvis")
        self.dots.persona = mode
        if mode == "ultron":
            sheet = self.styleSheet()
            replacements = {accent: "#ff8176", "#111310": "#0d0e12", "#191b17": "#15151b", "#1d211a": "#1b1b23", "#181c16": "#14141b", "#2b3026": "#3e292e", "#2a2d26": "#35232a", "#292f20": "#382128", "#303925": "#382128", "#2c3226": "#30242b", "#293022": "#30242b", "#131710": "#121219", "#414937": "#53323a", "#3b4432": "#48303a", "#4d583f": "#603a44", "#202817": "#250c10", "#eef6d7": "#ffb4aa", "#242b1e": "#28202a", "#46503b": "#70404b", "#b8bcb0": "#c4a0a7", "#adb2a5": "#b3a3aa"}
            for old, new in replacements.items():
                sheet = sheet.replace(old, new)
            sheet += "#card, #heroCard { border-radius: 12px; } QPushButton, QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox { border-radius: 8px; } #brand { color: #ff8176; }"
            self.setStyleSheet(sheet)
            self.dots.accent = QColor("#ff8176")
            self.brand.setText("ULTRON")
            self.hero_title.setText("Системы под контролем.\nОжидаю команд.")
            self.hero_eyebrow.setText("ULTRON PROTOCOL / LOCAL CONTROL")
        else:
            self.brand.setText("JARVIS")
            self.hero_title.setText("Твой ПК.\nПод твоим голосом.")
            self.hero_eyebrow.setText("МЕНЬШЕ КЛИКОВ. БОЛЬШЕ ДЕЙСТВИЙ.")
        self.dots.update()

    def switch_persona(self, mode):
        if mode not in {"jarvis", "ultron"}:
            return
        self.settings["voice_mode"] = mode
        self.voice_text.setText(f"«{self.settings['wake_word'].capitalize()}, который час?»")
        self.speaker.mode = mode
        for combo in (self.persona_switch, self.voice_modes):
            combo.blockSignals(True)
            combo.setCurrentIndex(combo.findData(mode))
            combo.blockSignals(False)
        self.store.write("settings.json", self.settings)
        self.apply_theme()
        self.status_label.setText(f"Режим {mode.title()}: голос и оформление переключены.")

    def navigate(self, index):
        self.pages.setCurrentIndex(index)
        self.page_title.setText(["Ассистент", "Команды", "История", "Настройки"][index])
        for i, b in enumerate(self.nav):
            b.setChecked(i == index)

    @staticmethod
    def clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def refresh_commands(self):
        self.clear_layout(self.command_grid)
        query = self.search.text().casefold()
        filtered = [c for c in self.commands if query in (c["title"] + " ".join(c["phrases"])).casefold()]
        for i, c in enumerate(filtered):
            card = panel()
            layout = QVBoxLayout(card)
            layout.setContentsMargins(20, 18, 20, 18)
            layout.addWidget(label(c["title"], "cardTitle", True))
            layout.addWidget(label(" / ".join(c["phrases"]), "muted", True))
            layout.addWidget(label(f"{len(c['actions'])} действий  ·  {'включена' if c['enabled'] else 'выключена'}" + ("  ·  подтверждение" if c["confirm"] else ""), "tiny", True))
            row = QHBoxLayout()
            row.addWidget(button("Запустить", lambda checked=False, cmd=c: self.execute([cmd], cmd["title"])))
            row.addWidget(button("Изменить", lambda checked=False, cmd=c: self.edit_command(cmd)))
            row.addWidget(button("×", lambda checked=False, cmd=c: self.delete_command(cmd), "smallButton"))
            layout.addLayout(row)
            self.command_grid.addWidget(card, i//2, i%2)
        self.count_label.setText(f"{sum(c['enabled'] for c in self.commands):02d} КОМАНД ГОТОВЫ К ЗАПУСКУ")

    def edit_command(self, command=None):
        dialog = CommandEditor(self, command)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            updated = [c for c in self.commands if not command or c["id"] != command["id"]] + [dialog.result_command]
            try:
                self.commands = validate_collection(updated)
                self.store.write("commands.json", self.commands)
            except ValueError as exc:
                QMessageBox.warning(self, "Не удалось сохранить", str(exc))
            self.refresh_commands()

    def delete_command(self, command):
        if QMessageBox.question(self, "Удалить команду?", command["title"], QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.commands = [c for c in self.commands if c["id"] != command["id"]]
            self.store.write("commands.json", self.commands)
            self.refresh_commands()

    def import_commands(self):
        path, _ = QFileDialog.getOpenFileName(self, "Импортировать команды", "", "JSON (*.json)")
        if not path:
            return
        try:
            imported = validate_collection(json.loads(Path(path).read_text(encoding="utf-8")))
            # Imported commands remain disabled until individually reviewed in the editor.
            for command in imported:
                command["enabled"] = False
            updated = {c["id"]: c for c in self.commands}
            updated.update({c["id"]: c for c in imported})
            self.commands = validate_collection(list(updated.values()))
            self.store.write("commands.json", self.commands)
            self.refresh_commands()
            self.status_label.setText("Импорт завершён. Откройте команды, проверьте действия и включите нужные.")
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Ошибка импорта", str(exc))

    def export_commands(self):
        path, _ = QFileDialog.getSaveFileName(self, "Экспортировать команды", "jarvis-commands.json", "JSON (*.json)")
        if path:
            Path(path).write_text(json.dumps(self.commands, ensure_ascii=False, indent=2), encoding="utf-8")

    def refresh_history(self):
        self.clear_layout(self.history_layout)
        entries = self.store.history()
        if not entries:
            self.history_layout.addWidget(label("Пока тихо. Запусти первую команду.", "muted"))
        for entry in entries:
            card = panel()
            layout = QVBoxLayout(card)
            layout.setContentsMargins(20, 16, 20, 16)
            layout.addWidget(label(("✓  " if entry["ok"] else "!  ") + entry["phrase"], "cardTitle", True))
            layout.addWidget(label(entry["message"], "muted", True))
            layout.addWidget(label(entry["time"], "tiny"))
            self.history_layout.addWidget(card)

    def clear_history(self):
        self.store.write("history.json", [])
        self.refresh_history()

    def run_by_id(self, key):
        command = next((c for c in self.commands if c["id"] == key), None)
        if command:
            self.execute([command], command["title"])
        else:
            self.response.setText("Команда удалена. Добавьте её в редакторе.")

    def run_text(self):
        phrase = self.command_input.text().strip()
        if phrase:
            self.handle_phrase(phrase, voice=False)

    def handle_phrase(self, phrase, voice=True):
        result = match_phrase(phrase, self.commands, self.settings["wake_word"], voice and self.settings["require_wake_word"])
        if not result.commands:
            self.response.setText(result.reason)
            return
        self.voice_text.setText(phrase)
        self.execute(result.commands, phrase)

    def execute(self, commands, phrase):
        if any(not c.get("enabled", True) for c in commands):
            self.response.setText("Команда выключена. Включите её в редакторе.")
            return
        if self.runner and self.runner.isRunning():
            self.response.setText("Сценарий уже выполняется. Дождитесь завершения или остановите его.")
            return
        if self.listener:
            self.listener.suspended.set()
        if any(c.get("confirm") for c in commands):
            answer = QMessageBox.question(self, "Подтвердить выполнение", "\n".join(c["title"] for c in commands), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                if self.listener:
                    self.listener.suspended.clear()
                self.response.setText("Выполнение отменено.")
                return
        self.pending_phrase = phrase
        self.runner = RunWorker(self.executor, commands)
        self.runner.progress.connect(self.response.setText)
        self.runner.result.connect(self.run_finished)
        self.runner.finished.connect(self.run_thread_finished)
        self.stop_button.setVisible(True)
        self.runner.start()

    def run_finished(self, ok, message):
        self.response.setText(message)
        self.store.record(dict(time=datetime.now().astimezone().isoformat(timespec="seconds"), phrase=self.pending_phrase, ok=ok, message=message))
        self.refresh_history()
        self.stop_button.setVisible(False)
        if ok and self.runner and not any(a["type"] in {"time", "speak"} for c in self.runner.commands for a in c["actions"]):
            self.speaker.say("Запрос выполнен, сэр")

    def run_thread_finished(self):
        if self.listener:
            self.listener.suspended.clear()

    def cancel_run(self):
        if self.runner:
            self.runner.cancel.set()

    def toggle_listening(self):
        if self.listener and self.listener.isRunning():
            self.listener.stop()
            self.listen_button.setEnabled(False)
            self.listen_button.setText("Останавливаю…")
            return
        listener_settings = dict(self.settings)
        enabled_commands = validate_collection([command for command in self.commands if command["enabled"]])
        listener_settings["command_phrases"] = [phrase for command in enabled_commands for phrase in command["phrases"]]
        self._cloud_recognizer = None
        cloud_transcriber = None
        if self.settings.get("recognition_backend", "offline") == "gemini":
            try:
                key = load_gemini_key()
                if not key:
                    self.navigate(3)
                    self.refresh_recognition_status()
                    self.status_label.setText("Сохраните API-ключ Google или выберите офлайн-режим.")
                    return
                self._cloud_recognizer = GeminiCommandRecognizer(key)
            except CredentialsError as exc:
                self.navigate(3)
                self.status_label.setText(str(exc))
                return
            client = self._cloud_recognizer
            wake = self.settings["wake_word"]
            listener_settings["require_wake_word"] = True
            def cloud_transcriber(pcm, sample_rate, local_text):
                return client.recognize(pcm, sample_rate, local_text, enabled_commands, wake)
        model = find_model(self.settings, self.store.root)
        if not model:
            self._cloud_recognizer = None
            self.navigate(3)
            self.status_label.setText("Выберите или загрузите модель. Без модели доступны команды текстом и кнопками.")
            return
        self.listener = Listener(model, self.settings["microphone"], self.speaker.active,
                                 settings=listener_settings, cloud_transcriber=cloud_transcriber)
        self.listener.recognized.connect(self.handle_phrase)
        self.listener.partial.connect(lambda text: self.voice_text.setText(text or "Слушаю…"))
        self.listener.state.connect(self.status_label.setText)
        self.listener.failed.connect(self.status_label.setText)
        self.listener.level.connect(self.voice_level)
        self.listener.finished.connect(self.listening_stopped)
        self.listener.start()
        self.dots.listening = True
        self.listen_button.setText("■  Выключить микрофон")
        self.voice_badge.setText("МИКРОФОН ВКЛ")
        if self.tray:
            self.tray.setToolTip("JARVIS DOT · микрофон включён")

    def voice_level(self, value):
        self.dots.level = value

    def listening_stopped(self):
        if self.listener:
            self.listener.cloud_transcriber = None
        self._cloud_recognizer = None
        self.dots.listening = False
        self.listen_button.setEnabled(True)
        self.listen_button.setText("●  Включить микрофон")
        self.voice_badge.setText("ОЖИДАНИЕ")
        if self.tray:
            self.tray.setToolTip("JARVIS DOT · микрофон выключен")

    def refresh_model(self):
        model = find_model(self.settings, self.store.root)
        self.model_status.setText(f"Готова к офлайн-работе: {model}" if model else "Модель не установлена. Скачайте один раз или выберите папку модели.")

    def choose_model(self):
        path = QFileDialog.getExistingDirectory(self, "Папка модели Vosk")
        if path:
            self.model_path.setText(path)

    def download_model(self):
        if self.downloader and self.downloader.isRunning():
            return
        self.downloader = ModelWorker(self.store.root)
        self.download_button.setEnabled(False)
        self.downloader.progress.connect(lambda percent: self.download_button.setText(f"Загрузка · {percent}%"))
        self.downloader.result.connect(self.download_finished)
        self.downloader.start()

    def download_finished(self, ok, message):
        self.download_button.setEnabled(True)
        self.download_button.setText("Скачать модель · 45 МБ")
        self.status_label.setText("Модель установлена" if ok else message)
        self.refresh_model()

    def save_settings(self):
        if self.listener and self.listener.isRunning():
            self.status_label.setText("Выключите микрофон перед изменением настроек.")
            return
        if not self.wake.text().strip():
            self.status_label.setText("Введите имя помощника.")
            return
        self.settings.update(wake_word=self.wake.text().strip(),
            require_wake_word=self._offline_require_wake if self.recognition_backend.currentData() == "gemini" else self.require_wake.isChecked(),
            spoken_replies=self.spoken.isChecked(), voice_mode=self.voice_modes.currentData(), model_path=self.model_path.text().strip(),
            microphone=self.microphones.currentData(), accent=self.accents.currentData(), close_to_tray=self.close_to_tray.isChecked())
        self.settings.update(use_voice_pack=self.use_pack.isChecked(), clone_enabled=self.clone_enabled.isChecked(),
            clone_python=self.clone_python.text().strip(), clone_model=self.clone_model.text().strip())
        self.settings.update(recognition_backend=self.recognition_backend.currentData(),
            speech_threshold=self.speech_threshold.value(),
            min_recognition_confidence=self.recognition_confidence.value() / 100)
        self.store.write("settings.json", self.settings)
        self.speaker.enabled = self.settings["spoken_replies"] and not self.test_mode
        self.speaker.mode = self.settings["voice_mode"]
        self.configure_speaker()
        self.apply_theme()
        self.refresh_model()
        self.refresh_recognition_status()
        self.status_label.setText("Настройки сохранены.")

    def preview_voice(self):
        self.speaker.mode = self.voice_modes.currentData()
        phrase = "Добрый вечер. Все системы готовы. Ожидаю ваших команд." if self.speaker.mode == "jarvis" else "Я на связи. Системы под моим контролем. Назови свою команду."
        self.speaker.say(phrase, force=True)

    def configure_speaker(self):
        self.speaker.use_pack = self.settings["use_voice_pack"]
        self.speaker.clone_enabled = self.settings["clone_enabled"]
        self.speaker.clone_python = self.settings["clone_python"]
        self.speaker.clone_model = self.settings["clone_model"]

    def preview_recording(self):
        self.speaker.say("К вашим услугам, сэр", force=True, use_pack=True)

    def setup_tray(self):
        self.tray = None
        if not self.test_mode and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self.app_icon, self)
            self.tray.setToolTip("JARVIS DOT · микрофон выключен")
            menu = QMenu(self)
            menu.addAction("Открыть", self.restore)
            menu.addAction("Микрофон вкл / выкл", self.toggle_listening)
            menu.addSeparator()
            menu.addAction("Выйти", self.quit_app)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(lambda reason: self.restore() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
            self.tray.show()

    def restore(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_app(self):
        self._quitting = True
        self.close()

    def shutdown(self):
        if self.listener and self.listener.isRunning():
            self.listener.stop()
            self.listener.wait(6000)
        if self.runner and self.runner.isRunning():
            self.runner.cancel.set()
            self.runner.wait(15000)
        self.speaker.close()
        if self.tray:
            self.tray.hide()

    def closeEvent(self, event):
        if not self._quitting and self.settings["close_to_tray"] and self.tray:
            self.hide()
            event.ignore()
            return
        if self.downloader and self.downloader.isRunning():
            self.status_label.setText("Дождитесь завершения загрузки модели перед выходом.")
            event.ignore()
            return
        self.shutdown()
        event.accept()
