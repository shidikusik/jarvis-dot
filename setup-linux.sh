#!/bin/sh
set -eu
cd -- "$(dirname -- "$0")"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/download_model.py
.venv/bin/python scripts/download_voices.py
printf 'Ready. Run: sh start-linux.sh\n'
