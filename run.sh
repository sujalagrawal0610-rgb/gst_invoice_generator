#!/usr/bin/env bash
# One-click start for macOS / Linux:  ./run.sh   (or double-click run.command on Mac)
cd "$(dirname "$0")"
if [ ! -d venv ]; then echo "Creating virtual environment..."; python3 -m venv venv || exit 1; fi
source venv/bin/activate
pip install -q -r requirements.txt || exit 1
[ -f .env ] || { cp .env.example .env; echo ">> Created .env - open it and add your Gmail App Password for real OTP e-mails."; }
python app.py
