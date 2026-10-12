import threading

from PySide6.QtCore import QThread, Signal

from jarvis.models import install_model


class RunWorker(QThread):
    progress = Signal(str)
    result = Signal(bool, str)

    def __init__(self, executor, commands):
        super().__init__()
        self.executor, self.commands = executor, commands
        self.cancel = threading.Event()

    def run(self):
        try:
            self.result.emit(True, self.executor.execute(self.commands, self.cancel, self.progress.emit))
        except Exception as exc:
            self.result.emit(False, str(exc))


class ModelWorker(QThread):
    progress = Signal(int)
    result = Signal(bool, str)

    def __init__(self, root):
        super().__init__()
        self.root = root

    def run(self):
        try:
            path = install_model(self.root, self.progress.emit)
            self.result.emit(True, str(path))
        except Exception as exc:
            self.result.emit(False, str(exc))
