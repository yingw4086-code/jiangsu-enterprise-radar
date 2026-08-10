$ErrorActionPreference = "Stop"

Set-Location -Path $PSScriptRoot

if (Test-Path ".\.venv\Scripts\python.exe") {
    $python = ".\.venv\Scripts\python.exe"
} else {
    $python = "python"
}

& $python -m data_source.multi_source_runner run-once --min-records 50
