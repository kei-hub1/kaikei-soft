@echo off
cd /d "%~dp0"
where pyw >nul 2>nul && (start "" pyw "%~dp0zaimu_gui.pyw" & exit /b 0)
where pythonw >nul 2>nul && (start "" pythonw "%~dp0zaimu_gui.pyw" & exit /b 0)
echo Python ‚ªŒ©‚Â‚©‚è‚Ü‚¹‚ñB
pause
