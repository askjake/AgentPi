@echo off
setlocal
if not "%~1"=="" if /I not "%~1"=="--restart" (
    echo Usage: qualify-execution-boundary.cmd [--restart]
    exit /b 2
)
pushd "%~dp0..\.." || exit /b 2
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONDONTWRITEBYTECODE=1"
if not exist ".venv-windows\Scripts\python.exe" goto missing
if not exist "dish-chat\backend\.venv-windows\Scripts\python.exe" goto missing

echo === SOURCE IDENTITY ===
git branch --show-current
if errorlevel 1 goto failed
git rev-parse HEAD
if errorlevel 1 goto failed

echo === FOCUSED EXECUTION-BOUNDARY TESTS ===
.venv-windows\Scripts\python.exe -m pytest -q tests\test_planner_execution_boundary.py
if errorlevel 1 goto failed

echo === ROOT REGRESSION SUITE ===
.venv-windows\Scripts\python.exe -m pytest -q
if errorlevel 1 goto failed

echo === DISHCHAT WINDOWS SUITE (INCLUDING LIVE GRAPH IMPORT PATH) ===
pushd dish-chat\backend || goto failed
.venv-windows\Scripts\python.exe -m pytest -q tests_windows
set "DISH_TEST_RC=%ERRORLEVEL%"
popd
if not "%DISH_TEST_RC%"=="0" goto failed

echo === PATCH VERIFIER ===
.venv-windows\Scripts\python.exe tests\patch_verify\test_integration.py
if errorlevel 1 goto failed
if /I not "%~1"=="--restart" goto passed

echo === RESTART REQUESTED: IN-MEMORY CHECKPOINTS WILL NOT SURVIVE ===
powershell -NoProfile -ExecutionPolicy Bypass -File deployment\windows\stop.ps1
if errorlevel 1 goto failed
powershell -NoProfile -ExecutionPolicy Bypass -File deployment\windows\start.ps1 -OpenBrowser
if errorlevel 1 goto failed
powershell -NoProfile -ExecutionPolicy Bypass -File deployment\windows\verify.ps1
if errorlevel 1 goto failed
.venv-windows\Scripts\python.exe deployment\windows\verify-live-planner.py
if errorlevel 1 goto failed

:passed
echo EXECUTION_BOUNDARY_QUALIFICATION_PASS
popd
exit /b 0

:missing
echo BLOCKED: Both existing Windows virtual environments are required.
goto failed

:failed
echo EXECUTION_BOUNDARY_QUALIFICATION_FAILED - later stages were not run.
popd
exit /b 1
