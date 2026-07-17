$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot "..\.venv\Scripts\python.exe"

Push-Location $ProjectRoot
try {
    & $Python -m app.main watch --time "08:30" --config "$ProjectRoot\config\sites.json" --output-dir "$ProjectRoot\data\excel" --state-path "$ProjectRoot\data\state\seen_links.json"
}
finally {
    Pop-Location
}

