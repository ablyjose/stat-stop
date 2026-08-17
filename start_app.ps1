$ScriptRoot = $PSScriptRoot

# Start Backend
Write-Host "Starting Backend..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$ScriptRoot/backend'; python -m uvicorn main:app --reload --port 8000"

# Start Frontend
Write-Host "Starting Frontend..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$ScriptRoot/frontend'; npm run dev"

Write-Host "Servers launched in new windows."
