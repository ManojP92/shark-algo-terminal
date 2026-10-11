# ==============================================================================
#  SHARK ALGO TERMINAL — ONE-CLICK LOCAL LAUNCHER
#  Starts Node Data Bridge (3001), FastAPI Strategy Engine (5001), and React UI (5000)
# ==============================================================================

Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "   SHARK ALGO — INSTITUTIONAL QUANT TRADING TERMINAL  " -ForegroundColor Cyan
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host ""

$BaseDir = $PSScriptRoot

# 1. Start Node Data Bridge (Port 3001)
Write-Host "[1/3] Starting Node Data Bridge on http://localhost:3001..." -ForegroundColor Yellow
$nodeProcess = Start-Process -FilePath "node" -ArgumentList "server.mjs" -WorkingDirectory "$BaseDir\shark-algo-portal\backend-node" -PassThru

# 2. Start Python FastAPI Strategy Engine (Port 5001)
Write-Host "[2/3] Starting Python FastAPI Strategy Engine on http://localhost:5001..." -ForegroundColor Yellow
$pyProcess = Start-Process -FilePath "python" -ArgumentList "-m uvicorn api_server:app --host 0.0.0.0 --port 5001" -WorkingDirectory "$BaseDir\shark-algo-portal\backend-python" -PassThru

# 3. Start React Web Dashboard (Port 5000)
Write-Host "[3/3] Starting React Web Dashboard on http://localhost:5000..." -ForegroundColor Yellow
$uiProcess = Start-Process -FilePath "npm" -ArgumentList "run dev" -WorkingDirectory "$BaseDir\shark-algo-portal\frontend" -PassThru

Start-Sleep -Seconds 3

Write-Host ""
Write-Host "[+] All services launched successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "  Dashboard URL : http://localhost:5000" -ForegroundColor White
Write-Host "  API Docs      : http://localhost:5001/docs" -ForegroundColor White
Write-Host "  Node Bridge   : http://localhost:3001/health" -ForegroundColor White
Write-Host ""
Write-Host "Press Ctrl+C or close the terminal to terminate." -ForegroundColor DarkGray

# Wait for exit
try {
    Wait-Process -Id $uiProcess.Id
} finally {
    Stop-Process -Id $nodeProcess.Id -ErrorAction SilentlyContinue
    Stop-Process -Id $pyProcess.Id -ErrorAction SilentlyContinue
}
