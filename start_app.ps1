$ScriptRoot = $PSScriptRoot
$PythonPath = (Get-Command python -CommandType Application -ErrorAction Stop).Path

# Start Backend
Write-Host "Starting Backend..."
$BackendProc = Start-Process -FilePath $PythonPath[0] -WorkingDirectory $ScriptRoot `
    -ArgumentList '-m', 'uvicorn', 'backend.main:app', '--reload', '--port', '8000' `
    -WindowStyle Hidden -PassThru

# Start Frontend
Write-Host "Starting Frontend..."
$FrontendProc = Start-Process powershell -WorkingDirectory (Join-Path $ScriptRoot 'frontend') `
    -ArgumentList '-NoProfile', '-Command', 'npm run dev' `
    -WindowStyle Hidden -PassThru

# Save PIDs for stop_app.ps1
$PidFile = Join-Path $ScriptRoot 'running_pids.txt'
"$($BackendProc.Id)`n$($FrontendProc.Id)" | Set-Content -Path $PidFile

Write-Host "Servers launched in the background. Open http://localhost:5173."
Write-Host "Run .\stop_app.ps1 to stop both servers."
