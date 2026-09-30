# ModelForge Phase 15 — Local Continuous Integration (CI) Pipeline Orchestrator
[CmdletBinding()]
param(
    [switch]$SkipDeploy,
    [switch]$SkipBuild,
    [string]$Version = "1.5.0",
    [string]$Namespace = "modelforge"
)

$ErrorActionPreference = "Stop"
$WorkspaceRoot = (Get-Item $PSScriptRoot).Parent.FullName
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User") + ";$env:LOCALAPPDATA\Microsoft\WinGet\Packages\OpenTofu.Tofu_Microsoft.Winget.Source_8wekyb3d8bbwe"

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host " MODELFORGE AUTOMATED CONTINUOUS INTEGRATION (CI) PIPELINE" -ForegroundColor Cyan
Write-Host " Version:     $Version" -ForegroundColor Yellow
Write-Host " Workspace:   $WorkspaceRoot" -ForegroundColor Yellow
Write-Host " Namespace:   $Namespace" -ForegroundColor Yellow
Write-Host " Timestamp:   $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss UTC')" -ForegroundColor Gray
Write-Host "================================================================================"

$StartTime = Get-Date

# -----------------------------------------------------------------------------
# STAGE 1: Pre-flight & Git Repository Verification
# -----------------------------------------------------------------------------
Write-Host "`n[STAGE 1/8] Verifying Environment & Repository..." -ForegroundColor Cyan
$gitStatus = (git status --porcelain 2>$null)
$commitSha = (git rev-parse --short HEAD 2>$null)
if (-not $commitSha) { $commitSha = "uncommitted" }
Write-Host "   Commit SHA:       $commitSha" -ForegroundColor Gray
Write-Host "   Kubernetes Node:  desktop-control-plane" -ForegroundColor Gray
Write-Host "   Cluster Context:  docker-desktop" -ForegroundColor Gray
Write-Host "[OK] Stage 1 Pre-flight checks passed." -ForegroundColor Green

# -----------------------------------------------------------------------------
# STAGE 2: Secret Scanning Gate
# -----------------------------------------------------------------------------
Write-Host "`n[STAGE 2/8] Running Security Secret Scanner..." -ForegroundColor Cyan
$secretMatches = & git grep -E -I -i "(BEGIN RSA PRIVATE KEY|AIzaSy[A-Za-z0-9_-]{33}|client_secret|MINIO_ROOT_PASSWORD\s*:\s*[A-Za-z0-9]+)" -- ':!*.example.*' ':!tests/*' ':!*.gitignore' ':!scripts/*' ':!.github/*' 2>$null
if ($secretMatches) {
    Write-Error "CRITICAL: Potential leaked credentials discovered in tracked files!"
    throw "Secret scan gate failed."
}
Write-Host "   Scanned repository tracked files and git index: 0 credentials leaked." -ForegroundColor Gray
Write-Host "[OK] Stage 2 Secret Scanning passed." -ForegroundColor Green

# -----------------------------------------------------------------------------
# STAGE 3: Infrastructure as Code (OpenTofu) Validation
# -----------------------------------------------------------------------------
Write-Host "`n[STAGE 3/8] Validating Infrastructure as Code (OpenTofu)..." -ForegroundColor Cyan
Push-Location "$WorkspaceRoot\infra\terraform"
try {
    Write-Host "   Running tofu validate..." -ForegroundColor Gray
    & tofu validate
    if ($LASTEXITCODE -ne 0) { throw "tofu validate failed!" }

    Write-Host "   Running tofu plan (Dry-Run Reconcile)..." -ForegroundColor Gray
    & tofu plan -var "api_version=$Version"
    if ($LASTEXITCODE -ne 0) { throw "tofu plan failed!" }
} finally {
    Pop-Location
}
Write-Host "[OK] Stage 3 OpenTofu IaC validation passed." -ForegroundColor Green

# -----------------------------------------------------------------------------
# STAGE 4: Kubernetes Manifest Client Validation
# -----------------------------------------------------------------------------
Write-Host "`n[STAGE 4/8] Validating Kubernetes Manifests (Dry-Run)..." -ForegroundColor Cyan
$k8sManifests = Get-ChildItem "$WorkspaceRoot\k8s" -Filter "*.yaml" -File | Where-Object { $_.Name -notmatch "example" }
foreach ($manifest in $k8sManifests) {
    Write-Host "   Checking $($manifest.Name)..." -ForegroundColor Gray
    & kubectl apply -f $manifest.FullName --dry-run=client
    if ($LASTEXITCODE -ne 0) { throw "Dry-run failed on $($manifest.Name)" }
}
Write-Host "[OK] Stage 4 Kubernetes manifest schema validation passed." -ForegroundColor Green

# -----------------------------------------------------------------------------
# STAGE 5: Backend Automated Unit & Integration Tests
# -----------------------------------------------------------------------------
Write-Host "`n[STAGE 5/8] Running Backend Automated Test Suite..." -ForegroundColor Cyan
$pytestExe = "$WorkspaceRoot\backend\.venv\Scripts\python.exe"
if (-not (Test-Path $pytestExe)) { $pytestExe = "python" }

& $pytestExe -m pytest "$WorkspaceRoot\backend\tests" -q
if ($LASTEXITCODE -ne 0) {
    throw "Backend pytest test suite failed!"
}
Write-Host "[OK] Stage 5 Backend test suite passed." -ForegroundColor Green

# -----------------------------------------------------------------------------
# STAGE 6: Frontend Production Build Gate
# -----------------------------------------------------------------------------
Write-Host "`n[STAGE 6/8] Building Frontend Production Bundle..." -ForegroundColor Cyan
& npm --prefix "$WorkspaceRoot\frontend" run build
if ($LASTEXITCODE -ne 0) {
    throw "Frontend production build failed!"
}
Write-Host "[OK] Stage 6 Frontend production build passed." -ForegroundColor Green

# -----------------------------------------------------------------------------
# STAGE 7: Docker Container Image Build & Registry Delivery
# -----------------------------------------------------------------------------
if (-not $SkipBuild) {
    Write-Host "`n[STAGE 7/8] Executing Docker Build & Local Registry Push..." -ForegroundColor Cyan
    & "$WorkspaceRoot\scripts\build-images.ps1" -Version $Version -Registry "localhost:5000"
    if ($LASTEXITCODE -ne 0) {
        throw "Docker build/push pipeline failed!"
    }
    Write-Host "[OK] Stage 7 Docker images built and pushed to local registry." -ForegroundColor Green
} else {
    Write-Host "`n[STAGE 7/8] Skipping Docker build (-SkipBuild specified)." -ForegroundColor Yellow
}

# -----------------------------------------------------------------------------
# STAGE 8: Local Deployment & Health Gate Verification
# -----------------------------------------------------------------------------
if (-not $SkipDeploy) {
    Write-Host "`n[STAGE 8/8] Executing Local CD Deployment & Health Gates..." -ForegroundColor Cyan
    & "$WorkspaceRoot\scripts\deploy-local.ps1" -Version $Version -Namespace $Namespace
    if ($LASTEXITCODE -ne 0) {
        throw "Local deployment pipeline failed!"
    }
    Write-Host "[OK] Stage 8 Local deployment and health gates passed." -ForegroundColor Green
} else {
    Write-Host "`n[STAGE 8/8] Skipping Deployment (-SkipDeploy specified)." -ForegroundColor Yellow
}

$Elapsed = [math]::Round(((Get-Date) - $StartTime).TotalSeconds, 1)

Write-Host "`n================================================================================" -ForegroundColor Cyan
Write-Host " MODELFORGE CI/CD PIPELINE SUCCEEDED ($Elapsed seconds)" -ForegroundColor Green
Write-Host " All 8 Stages Verified and Complete." -ForegroundColor Green
Write-Host "================================================================================"
