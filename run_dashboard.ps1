$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot "..\.venv\Scripts\python.exe"

Push-Location $ProjectRoot
try {
    & $Python -m streamlit run dashboard.py --server.headless true --server.address 0.0.0.0 --server.port 8502 --server.enableCORS false --server.enableXsrfProtection false --browser.gatherUsageStats false
}
finally {
    Pop-Location
}
