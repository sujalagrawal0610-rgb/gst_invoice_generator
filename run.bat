@echo off
cd /d "%~dp0"
if not exist venv ( echo Creating virtual environment... & python -m venv venv )
call venv\Scripts\activate
pip install -q -r requirements.txt
if not exist .env ( copy .env.example .env >nul & echo ^>^> Created .env - open it and add your Gmail App Password for real OTP e-mails. )
python app.py
pause
