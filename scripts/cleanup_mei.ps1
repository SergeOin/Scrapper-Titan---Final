Param(
  [int]$Days = 1
)
$ErrorActionPreference = 'Stop'
$root = Join-Path $env:TEMP '*'
$now = Get-Date
$deleted = 0
$errors = 0
Get-ChildItem -Path $root -Directory -Filter '_MEI*' -ErrorAction SilentlyContinue | ForEach-Object {
  try {
    $age = $now - $_.LastWriteTime
    if ($age.TotalDays -ge $Days) {
      Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction Stop
      Write-Host "Deleted $($_.FullName)" -ForegroundColor DarkGray
      $deleted++
    }
  } catch {
    $errors++
  }
}
Write-Host ("Cleanup complete: deleted={0} errors={1}" -f $deleted, $errors)
