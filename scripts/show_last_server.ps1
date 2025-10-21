$p = Join-Path $Env:LOCALAPPDATA 'TitanScraper\last_server.json'
if (Test-Path -LiteralPath $p) {
  Get-Content -LiteralPath $p -Raw | Write-Output
} else {
  Write-Host 'missing'
}
