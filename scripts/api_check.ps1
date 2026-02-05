# Quick API check
$response = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/posts?per_page=5" -TimeoutSec 10
$response | ConvertTo-Json -Depth 10 | Out-File -FilePath "c:\Users\plogr\Desktop\Scrapper-Titan---Final\api_check.json" -Encoding UTF8
Write-Host "Done - check api_check.json"
