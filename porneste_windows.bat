@echo off
REM Rulează agentul pe calculator (Windows). Lasă fereastra deschisă.
cd /d %~dp0
chcp 65001 >nul

REM Pune aici numele canalului tău ntfy (același ca în aplicația de pe telefon):
set NTFY_TOPIC=pune-aici-canalul-tau

REM Opțional, Telegram:
REM set TELEGRAM_BOT_TOKEN=123456:ABC...
REM set TELEGRAM_CHAT_ID=123456789

python agent_oferte.py --bucla 15
pause
