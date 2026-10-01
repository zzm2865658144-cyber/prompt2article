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

echo.
echo   正在启动本地网页服务，马上会打开浏览器…
echo   关掉这个黑窗口就是停止服务。
echo.

%PY% -m prompt2article.webapp --port 8756 %*
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
  echo   启动失败，退出码 %RC%。上面有原因。
  echo   端口被占用的话换一个： 启动网页.bat --port 8757
  echo.
  pause
)
exit /b %RC%

:nopython
echo.
echo   找不到 Python。
echo   请安装 Python 3.10 或更高版本，安装时勾选 "Add python.exe to PATH"。
echo   下载： https://www.python.org/downloads/
echo.
pause
exit /b 1
