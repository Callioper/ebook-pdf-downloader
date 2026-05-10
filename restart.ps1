# Restart script: kills old instance, waits for port release, starts new one
$exe = "D:\opencode\book-downloader\backend\dist\ebook-pdf-downloader.exe"
$port = 8000

Write-Host "Stopping old instances..." -ForegroundColor Yellow
Get-Process -Name "ebook-pdf-downloader" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2

# Wait until port is free
$tries = 0
while ($tries -lt 30) {
    $inUse = netstat -ano | Select-String ":$port " | Select-String "LISTENING"
    if (-not $inUse) { break }
    Start-Sleep -Milliseconds 500
    $tries++
}

if ($tries -ge 30) {
    Write-Host "Port $port still in use after 15s. Force killing..." -ForegroundColor Red
    $pid = (netstat -ano | Select-String ":$port " | Select-String "LISTENING" | ForEach-Object { ($_ -split '\s+')[-5] } | Select-Object -First 1)
    if ($pid) { Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
}

Write-Host "Starting $exe..." -ForegroundColor Green
Start-Process -FilePath $exe -WorkingDirectory (Split-Path $exe) -WindowStyle Hidden
Start-Sleep -Seconds 3

Write-Host "Verifying..."
try {
    Invoke-WebRequest -Uri "http://127.0.0.1:$port/api/v1/config" -UseBasicParsing -TimeoutSec 10 | Out-Null
    Write-Host "Ready: http://127.0.0.1:$port" -ForegroundColor Green
} catch {
    Write-Host "Startup failed. Run in console window for errors:" -ForegroundColor Red
    Start-Process -FilePath $exe
}
