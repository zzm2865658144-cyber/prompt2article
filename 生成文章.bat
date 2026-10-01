@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

rem ---- 找一个可用的 Python ----
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY ( where py >nul 2>nul && set "PY=py" )
if not defined PY if exist "%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" set "PY=%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not defined PY goto nopython

rem ---- 还没有 .env 就先跑离线模式，保证能看到效果 ----
set "EXTRA=%*"
if not exist ".env" (
  echo.
  echo   [!] 还没配置 API Key，本次用离线模拟模式跑，内容是占位文字。
  echo       要生成真实文章：把 .env.example 复制为 .env，填入 P2A_API_KEY。
  echo.
  set "EXTRA=%* --offline"
)

%PY% -m prompt2article --interactive %EXTRA%
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
  echo   生成的文件在 output 文件夹里。
) else (
  echo   出错了，退出码 %RC%。上面有具体原因。
)
echo.
pause
exit /b %RC%

:nopython
echo.
echo   找不到 Python。
echo   请安装 Python 3.10 或更高版本，安装时勾选 "Add python.exe to PATH"。
echo   下载： https://www.python.org/downloads/
echo.
pause
exit /b 1
