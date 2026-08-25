@echo off
rem 四象小组件启动脚本：优先使用 pythonw（无控制台窗口）
cd /d "%~dp0"
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw main.py
    exit /b 0
)
python main.py
pause
