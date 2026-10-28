$ScriptRoot = $PSScriptRoot
$PythonPath = (Get-Command python -CommandType Application -ErrorAction Stop).Path

# Start Backend
Write-Host "Starting Backend..."
Start-Process -FilePath $PythonPath[0] -WorkingDirectory $ScriptRoot -ArgumentList '-m', 'uvicorn', 'backend.main:app', '--reload', '--port', '8000' -WindowStyle Hidden

# Start Frontend
Write-Host "Starting Frontend..."
Start-Process powershell -WorkingDirectory (Join-Path $ScriptRoot 'frontend') -ArgumentList '-NoProfile', '-Command', 'npm run dev' -WindowStyle Hidden

Write-Host "Servers launched in the background. Open http://localhost:5173."
