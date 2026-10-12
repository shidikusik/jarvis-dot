"""Native bundle entry point, with a local diagnostic log for GUI-only builds."""
import os
from pathlib import Path
import sys
import traceback

if __name__ == "__main__":
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("LOCALAPPDATA", Path.home()/".local/share")) / "JarvisDot"
        base.mkdir(parents=True, exist_ok=True)
        log = (base/"application.log").open("a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = log
        if sys.stderr is None:
            sys.stderr = log
    try:
        from jarvis.main import main
        main()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
