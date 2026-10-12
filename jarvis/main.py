from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description="JARVIS DOT — offline desktop assistant")
    parser.add_argument("--tts", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--speech-file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--smoke-test", action="store_true", help="Render UI and test a local command, then exit")
    parser.add_argument("--screenshot", type=Path, help="Save a screenshot during --smoke-test")
    args = parser.parse_args()
    if args.tts:
        from jarvis.voice import speak_process
        speak_process(args.speech_file)
        return
    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtCore import QTimer
    from jarvis.storage import Store
    from jarvis.ui import MainWindow
    app = QApplication(sys.argv[:1])
    app.setApplicationName("JARVIS DOT")
    app.setOrganizationName("JarvisDot")
    app.setStyle("Fusion")
    temporary = tempfile.TemporaryDirectory() if args.smoke_test else None
    try:
        window = MainWindow(Store(Path(temporary.name)) if temporary else None, test_mode=args.smoke_test)
    except Exception as exc:
        if args.smoke_test:
            raise
        QMessageBox.critical(None, "JARVIS DOT", str(exc))
        return
    window.show()
    if args.smoke_test:
        def check():
            try:
                window.handle_phrase("который час", voice=False)
                QTimer.singleShot(600, verify)
            except Exception:
                app.exit(1)

        def verify():
            entries = window.store.history()
            if not entries or not entries[0]["ok"]:
                app.exit(1)
                return
            if args.screenshot:
                args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                window.grab().save(str(args.screenshot))
            window.shutdown()
            app.exit(0)
        QTimer.singleShot(500, check)
        QTimer.singleShot(15000, lambda: app.exit(2))
    code = app.exec()
    if temporary:
        temporary.cleanup()
    raise SystemExit(code)
