@echo off
rem Build the Windows installable version of YT-Batch-Downloader-Mistu
rem (stages the app bundle and compiles the Inno Setup installer).
setlocal
where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
%PY% build_installer.py %*
endlocal & exit /b %errorlevel%
