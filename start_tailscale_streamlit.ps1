$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot "..\.venv\Scripts\python.exe"
$Dashboard = Join-Path $ProjectRoot "dashboard.py"
$TailscaleExe = $null

function Write-Section {
    param([string]$Text)
    Write-Host ""
    Write-Host "==== $Text ====" -ForegroundColor Cyan
}

Write-Section "Haimen Enterprise Radar startup check"

if (-not (Test-Path $Python)) {
    Write-Host "Python virtual environment was not found:" -ForegroundColor Red
    Write-Host $Python
    Read-Host "Press Enter to exit"
    exit 1
}

if (-not (Test-Path $Dashboard)) {
    Write-Host "dashboard.py was not found:" -ForegroundColor Red
    Write-Host $Dashboard
    Read-Host "Press Enter to exit"
    exit 1
}

$tailscale = Get-Command tailscale -ErrorAction SilentlyContinue
if ($tailscale) {
    $TailscaleExe = $tailscale.Source
}
elseif (Test-Path "C:\Program Files\Tailscale\tailscale.exe") {
    $TailscaleExe = "C:\Program Files\Tailscale\tailscale.exe"
}

if (-not $TailscaleExe) {
    Write-Host "Tailscale was not detected." -ForegroundColor Yellow
    Write-Host "Install and sign in to the Tailscale Windows client first."
    Write-Host "Install Tailscale on your phone and sign in with the same account."
}
else {
    Write-Section "Tailscale status"
    try {
        & $TailscaleExe status
    }
    catch {
        Write-Host "Tailscale status check failed. Please confirm the client is signed in." -ForegroundColor Yellow
    }

    try {
        $tailscaleIp = (& $TailscaleExe ip -4 | Select-Object -First 1).Trim()
        if ($tailscaleIp) {
            Write-Host ""
            Write-Host "Phone access URL:" -ForegroundColor Green
            Write-Host "http://$tailscaleIp`:8502" -ForegroundColor Green
        }
    }
    catch {
        Write-Host "Could not get the Tailscale IP yet." -ForegroundColor Yellow
    }
}

Write-Section "Start Streamlit"
Write-Host "Local URL: http://localhost:8502"
Write-Host "Tailscale URL: use http://TAILSCALE_IP:8502"

Push-Location $ProjectRoot
try {
    & $Python -m streamlit run dashboard.py --server.headless true --server.address 0.0.0.0 --server.port 8502 --server.enableCORS false --server.enableXsrfProtection false --browser.gatherUsageStats false
}
finally {
    Pop-Location
}
