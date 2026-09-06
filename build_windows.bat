@echo off
REM build_windows.bat — Script de build Hilo pour Windows (via Python Thonny)

SET PYTHON="C:\Program Files (x86)\Thonny\python.exe"
SET PIP="C:\Program Files (x86)\Thonny\Scripts\pip.bat"

echo ============================================
echo   Build Hilo.exe — Windows (Thonny Python)
echo ============================================

REM 1. Vérifier Python
%PYTHON% --version
IF %ERRORLEVEL% NEQ 0 (
    echo ERREUR : Python Thonny introuvable.
    pause
    exit /b 1
)

REM 2. Installer les dépendances
echo.
echo [1/3] Installation des dependances...
%PIP% install flask pdfplumber pandas pyinstaller pillow requests --quiet
IF %ERRORLEVEL% NEQ 0 (
    echo ERREUR lors de l'installation des dependances.
    pause
    exit /b 1
)

REM 3. Nettoyer les anciens builds
echo.
echo [2/3] Nettoyage des anciens builds...
IF EXIST dist rmdir /s /q dist
IF EXIST build rmdir /s /q build

REM 4. Lancer PyInstaller
echo.
echo [3/3] Compilation avec PyInstaller...
%PYTHON% -m PyInstaller hilo.spec
IF %ERRORLEVEL% NEQ 0 (
    echo ERREUR lors de la compilation PyInstaller.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   BUILD TERMINE !
echo   Fichier : dist\Hilo.exe
echo ============================================
pause
