<#!
.SYNOPSIS
 Uninstalls TitanScraper Windows service.
#>
param(
    [string]$ServiceName = 'TitanScraper'
)

Write-Host "[service-uninstall] Stopping $ServiceName" -ForegroundColor Cyan
& sc.exe stop $ServiceName | Write-Host
Start-Sleep -Seconds 3
Write-Host "[service-uninstall] Deleting $ServiceName" -ForegroundColor Yellow
& sc.exe delete $ServiceName | Write-Host
Write-Host "[service-uninstall] Removed." -ForegroundColor Green
