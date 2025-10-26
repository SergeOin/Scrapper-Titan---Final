<#!
.SYNOPSIS
  Finds and disables/removes any autostart entries (Scheduled Tasks, Startup folder, Run registry, and optional Windows service)
  that reference TitanScraper, Titan Scraper, TitanScraper.exe, or trigger.ps1. Safe by default (disables) and idempotent.

.DESCRIPTION
  This helper is intended for cases where a previous install or experiment left a scheduled task like
  powershell.exe -File %LOCALAPPDATA%\TitanScraper\trigger.ps1 that keeps popping up a console window.
  Run it on the affected machine.

.PARAMETER Remove
  If set, matching items are deleted instead of only disabled.

.PARAMETER IncludeService
  If set, also tries to stop and delete the Windows service named 'TitanScraper' (or a custom name).

.PARAMETER ServiceName
  Name of the service to target when -IncludeService is specified. Defaults to 'TitanScraper'.

.EXAMPLE
  # Preview what would be changed
  .\scripts\cleanup_autostart.ps1 -WhatIf

.EXAMPLE
  # Disable all matching entries (recommended, reversible)
  .\scripts\cleanup_autostart.ps1

.EXAMPLE
  # Remove everything including the Windows service
  .\scripts\cleanup_autostart.ps1 -Remove -IncludeService
#>
[CmdletBinding(SupportsShouldProcess=$true, ConfirmImpact='Medium')]
param(
  [switch]$Remove,
  [switch]$IncludeService,
  [string]$ServiceName = 'TitanScraper'
)

$ErrorActionPreference = 'Stop'
$patterns = @('TitanScraper','Titan Scraper','trigger.ps1','TitanScraper.exe')

function Test-Match($text){
  foreach($p in $patterns){ if($text -match [Regex]::Escape($p)){ return $true } }
  return $false
}

Write-Host "[cleanup] Searching for autostart entries matching: $($patterns -join ', ')" -ForegroundColor Cyan

# 1) Scheduled tasks: prefer Get-ScheduledTask; fallback to schtasks if unavailable
try {
  $ts = $null
  try { $ts = Get-ScheduledTask -ErrorAction Stop } catch { $ts = $null }
  if($ts){
    $hits = @()
    foreach($t in $ts){
      $act = $null
      try { $act = ($t.Actions | ForEach-Object { ("$($_.Execute) $($_.Arguments)").Trim() }) -join '; ' } catch {}
      if([string]::IsNullOrWhiteSpace($act)){ continue }
      if(Test-Match $act){ $hits += [PSCustomObject]@{ TaskName=$t.TaskName; TaskPath=$t.TaskPath; Action=$act } }
    }
    foreach($h in $hits){
      $tn = $h.TaskName; $tp = $h.TaskPath
      $what = if($Remove){'delete'} else {'disable'}
      if($PSCmdlet.ShouldProcess("$tp$tn", "Get-ScheduledTask/${what}")){
        try {
          if($Remove){ Unregister-ScheduledTask -TaskName $tn -TaskPath $tp -Confirm:$false }
          else { Disable-ScheduledTask -TaskName $tn -TaskPath $tp | Out-Null }
          Write-Host "[cleanup] Scheduled Task ${what}: $tp$tn" -ForegroundColor Yellow
        } catch { Write-Warning "[cleanup] Failed to ${what} task $tp$tn: $_" }
      }
    }
    if(-not $hits){ Write-Host "[cleanup] No Scheduled Tasks matched." -ForegroundColor DarkGray }
  } else {
    # Fallback to schtasks with CSV parsing
    $csv = & schtasks /Query /V /FO CSV 2>$null | Out-String
    if($csv){
      $rows = $csv | ConvertFrom-Csv
      $taskMatches = $rows | Where-Object { $_.'Task To Run' -and (Test-Match $_.'Task To Run') }
      foreach($m in $taskMatches){
        $tn = $m.'TaskName'
        $what = if($Remove){'delete'} else {'disable'}
        if ($PSCmdlet.ShouldProcess($tn, "schtasks /${what}")){
          try {
            if($Remove){ & schtasks /End /TN "$tn" 2>$null | Out-Null; & schtasks /Delete /TN "$tn" /F | Out-Null }
            else { & schtasks /Change /Disable /TN "$tn" | Out-Null }
            Write-Host "[cleanup] Scheduled Task ${what}: $tn" -ForegroundColor Yellow
          } catch { Write-Warning "[cleanup] Failed to ${what} task $tn: $_" }
        }
      }
      if(-not $taskMatches){ Write-Host "[cleanup] No Scheduled Tasks matched." -ForegroundColor DarkGray }
    } else { Write-Host "[cleanup] No scheduled tasks returned (permission or locale quirk)." -ForegroundColor DarkGray }
  }
} catch { Write-Warning "[cleanup] Scheduled task scan failed: $_" }

# 2) Startup folders
$startupDirs = @(
  Join-Path $Env:APPDATA 'Microsoft\\Windows\\Start Menu\\Programs\\Startup'),
  (Join-Path $Env:ProgramData 'Microsoft\\Windows\\Start Menu\\Programs\\StartUp')
$removedStartups = 0
foreach($dir in $startupDirs){
  if(Test-Path $dir){
    Get-ChildItem -LiteralPath $dir -File -ErrorAction SilentlyContinue | ForEach-Object {
      $f = $_.FullName
      $target = $null
      if($f.ToLower().EndsWith('.lnk')){
        try { $ws = New-Object -ComObject WScript.Shell; $sh = $ws.CreateShortcut($f); $target = $sh.TargetPath + ' ' + $sh.Arguments } catch {}
      } else { $target = Get-Content -LiteralPath $f -TotalCount 1 -ErrorAction SilentlyContinue }
      if($target -and (Test-Match $target)){
        $what = if($Remove){'remove'} else {'disable (rename .disabled)'}
        if($PSCmdlet.ShouldProcess($f, $what)){
          try {
            if($Remove){ Remove-Item -LiteralPath $f -Force }
            else { Rename-Item -LiteralPath $f -NewName ($_.Name + '.disabled') -Force }
            $removedStartups++
            Write-Host "[cleanup] Startup entry ${what}: $f" -ForegroundColor Yellow
          } catch { Write-Warning "[cleanup] Failed to modify startup item $f: $_" }
        }
      }
    }
  }
}
if($removedStartups -eq 0){ Write-Host "[cleanup] No Startup folder entries matched." -ForegroundColor DarkGray }

# 3) Registry Run keys
$runKeys = @(
  'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run',
  'HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run',
  'HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Run'
)
$changed = 0
foreach($rk in $runKeys){
  if(Test-Path $rk){
    $props = (Get-Item -LiteralPath $rk).Property
    foreach($name in $props){
      try {
        $val = (Get-ItemProperty -LiteralPath $rk -Name $name).$name
        if([string]::IsNullOrWhiteSpace($val)){ continue }
        if(Test-Match ([string]$val)){
          $what = if($Remove){'remove'} else {'disable (move to .Disabled)'}
          if($PSCmdlet.ShouldProcess("$rk\\$name", $what)){
            try {
              if($Remove){ Remove-ItemProperty -LiteralPath $rk -Name $name -Force }
              else {
                New-Item -Path ($rk + '.Disabled') -Force | Out-Null
                New-ItemProperty -Path ($rk + '.Disabled') -Name $name -Value $val -PropertyType String -Force | Out-Null
                Remove-ItemProperty -LiteralPath $rk -Name $name -Force
              }
              $changed++
              Write-Host "[cleanup] Run key ${what}: $rk/$name" -ForegroundColor Yellow
            } catch { Write-Warning "[cleanup] Failed to modify Run key $rk/$name: $_" }
          }
        }
      } catch {}
    }
  }
}
if($changed -eq 0){ Write-Host "[cleanup] No Run registry entries matched." -ForegroundColor DarkGray }

# 4) Leftover trigger.ps1 under %LOCALAPPDATA%\TitanScraper
$maybe = Join-Path $Env:LOCALAPPDATA 'TitanScraper\\trigger.ps1'
if(Test-Path $maybe){
  if($PSCmdlet.ShouldProcess($maybe, (if($Remove){'remove'} else {'rename .disabled'}))){
    try{
      if($Remove){ Remove-Item -LiteralPath $maybe -Force }
      else { Rename-Item -LiteralPath $maybe -NewName 'trigger.ps1.disabled' -Force }
      Write-Host "[cleanup] Tidied leftover: $maybe" -ForegroundColor Yellow
    } catch { Write-Warning "[cleanup] Failed to tidy $maybe: $_" }
  }
} else {
  Write-Host "[cleanup] No leftover trigger.ps1 file found in %LOCALAPPDATA%\\TitanScraper." -ForegroundColor DarkGray
}

# 5) Optional service cleanup
if($IncludeService){
  try {
    Write-Host "[cleanup] Stopping service $ServiceName (if present)" -ForegroundColor Cyan
    & sc.exe stop $ServiceName 2>$null | Out-Null
    Start-Sleep -Seconds 2
    if($Remove){
      Write-Host "[cleanup] Deleting service $ServiceName" -ForegroundColor Yellow
      & sc.exe delete $ServiceName 2>$null | Out-Null
    }
  } catch { Write-Warning "[cleanup] Service cleanup encountered an error: $_" }
}

Write-Host "[cleanup] Completed." -ForegroundColor Green
