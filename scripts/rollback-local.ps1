# ModelForge Phase 15 — Local Rollback Workflow
[CmdletBinding()]
param(
    [string]$Deployment = "modelforge-backend",
    [string]$Namespace = "modelforge",
    [switch]$All
)

$ErrorActionPreference = "Stop"

Write-Host "================================================================================" -ForegroundColor Red
Write-Host " MODELFORGE AUTOMATED ROLLBACK CONTROLLER" -ForegroundColor Red
Write-Host " Target Deployment: $Deployment (All: $($All.IsPresent))" -ForegroundColor Yellow
Write-Host " Target Namespace:  $Namespace" -ForegroundColor Yellow
Write-Host " Timestamp:         $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss UTC')" -ForegroundColor Gray
Write-Host "================================================================================"

$targets = if ($All) {
    @("modelforge-backend", "model-server", "modelforge-frontend")
} else {
    @($Deployment)
}

foreach ($target in $targets) {
    Write-Host "`n[+] 1. Capturing current revision for $target..." -ForegroundColor Cyan
    & kubectl rollout history deployment/$target -n $Namespace

    Write-Host "`n[+] 2. Triggering Rollback for deployment/$target..." -ForegroundColor Yellow
    & kubectl rollout undo deployment/$target -n $Namespace
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to trigger rollout undo for $target"
    }

    Write-Host "`n[+] 3. Waiting for rollback completion on deployment/$target..." -ForegroundColor Cyan
    & kubectl rollout status deployment/$target -n $Namespace --timeout=90s
    if ($LASTEXITCODE -ne 0) {
        throw "Rollback failed to complete for $target!"
    }
    Write-Host "[OK] Rollback rollout status confirmed Ready." -ForegroundColor Green
}

# Post-Rollback Health & Inference Verification
Write-Host "`n[+] 4. Verifying post-rollback platform health..." -ForegroundColor Cyan
$backendHealth = (curl.exe -s http://localhost:8000/api/health 2>$null)
if ($backendHealth -notmatch '"status"\s*:\s*"healthy"') {
    throw "Post-rollback health check failed: $backendHealth"
}
Write-Host "   [Health API] PASS: $backendHealth" -ForegroundColor Green

Write-Host "`n[+] 5. Verifying live model inference across restored deployment..." -ForegroundColor Cyan
$testPayload = '{"features": [[1.0, 2.0]]}'
$predResult = & kubectl exec -n $Namespace deploy/modelforge-backend -- python -c "import urllib.request, json; req = urllib.request.Request('http://model-server:8000/predict', data=b'$testPayload', headers={'Content-Type': 'application/json'}); print(json.loads(urllib.request.urlopen(req, timeout=5).read().decode()).get('predictions', []))" 2>$null
if ($predResult -notmatch "\[[0-9]+\]") {
    throw "Post-rollback inference test failed: $predResult"
}
Write-Host "   [Inference Verification] PASS (Prediction: $predResult)" -ForegroundColor Green

Write-Host "`n================================================================================" -ForegroundColor Green
Write-Host " ROLLBACK COMPLETED AND VERIFIED SUCCESSFULLY: WORKLOAD OPERATIONAL" -ForegroundColor Green
Write-Host "================================================================================"
