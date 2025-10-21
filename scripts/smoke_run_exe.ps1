Param(
    [string]$Path = 'dist\\TitanScraper.exe',
    [int]$Seconds = 8
)

if (-not (Test-Path -LiteralPath $Path)) {
    Write-Error "Executable not found at: $Path"
    exit 1
}

Write-Host "Starting $Path" -ForegroundColor Cyan
$p = Start-Process -FilePath $Path -PassThru
Start-Sleep -Seconds $Seconds

$alive = -not $p.HasExited
Write-Host "Alive after $Seconds seconds: $alive"

if ($alive) {
    $null = $p.CloseMainWindow()
    Start-Sleep -Seconds 3
    if (-not $p.HasExited) {
        Stop-Process -Id $p.Id -Force
        Write-Host "Terminated (forced)" -ForegroundColor Yellow
    } else {
        Write-Host "Closed cleanly" -ForegroundColor Green
    }
}

if ($p.HasExited) {
    Write-Host "ExitCode: $($p.ExitCode)" -ForegroundColor Gray
} else {
    Write-Host "Still running (process terminated)" -ForegroundColor Gray
}