$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot "..\.venv\Scripts\python.exe"
$EnvPath = Join-Path $ProjectRoot ".env"

if (Test-Path $EnvPath) {
    Get-Content $EnvPath | ForEach-Object {
        $Line = $_.Trim()
        if ($Line -and -not $Line.StartsWith("#") -and $Line.Contains("=")) {
            $Parts = $Line -split "=", 2
            $Name = $Parts[0].Trim()
            $Value = $Parts[1].Trim().Trim('"')
            [Environment]::SetEnvironmentVariable($Name, $Value, "Process")
        }
    }
}

Push-Location $ProjectRoot
try {
    & $Python -m app.main run-once --with-ai --config "$ProjectRoot\config\sites.json" --output-dir "$ProjectRoot\data\excel" --ai-output-dir "$ProjectRoot\data\ai" --state-path "$ProjectRoot\data\state\seen_links.json"
}
finally {
    Pop-Location
}
