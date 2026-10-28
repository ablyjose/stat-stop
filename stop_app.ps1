$ScriptRoot = $PSScriptRoot
$PidFile = Join-Path $ScriptRoot 'running_pids.txt'

if (Test-Path $PidFile) {
    $ids = Get-Content $PidFile | Where-Object { $_ -match '^\d+$' }
    foreach ($id in $ids) {
        # /T kills the entire process tree, /F forces termination
        & taskkill /T /F /PID $id 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Stopped process tree for PID $id"
        } else {
            Write-Warning "Could not stop process tree for PID ${id} (may have already exited)"
        }
    }
    Remove-Item $PidFile -Force
    Write-Host "All servers stopped."
} else {
    Write-Host "No PID file found. Attempting to locate processes manually..."

    $found = $false

    # Kill backend (uvicorn) by process tree
    Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -match 'uvicorn' -and $_.CommandLine -match 'backend\.main' } |
        ForEach-Object {
            & taskkill /T /F /PID $_.ProcessId 2>$null
            Write-Host "Stopped backend process tree $($_.ProcessId)"
            $found = $true
        }

    # Kill frontend (node/npm) by port 5173
    $portMatch = netstat -ano | Select-String ':5173\s' | ForEach-Object {
        if ($_ -match '\s(\d+)\s*$') { $Matches[1] }
    } | Select-Object -Unique

    foreach ($id in $portMatch) {
        & taskkill /T /F /PID $id 2>$null
        Write-Host "Stopped frontend process tree on port 5173 (PID $id)"
        $found = $true
    }

    if (-not $found) {
        Write-Host "No matching processes found."
    }
}
