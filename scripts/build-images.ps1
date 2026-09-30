# ModelForge Phase 15 — Docker Image Build & Local Registry Push Pipeline
[CmdletBinding()]
param(
    [string]$Version = "1.5.0",
    [string]$Registry = "localhost:5000",
    [switch]$SkipPush
)

$ErrorActionPreference = "Stop"
$WorkspaceRoot = (Get-Item $PSScriptRoot).Parent.FullName

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host " MODELFORGE DOCKER BUILD & REGISTRY PIPELINE" -ForegroundColor Cyan
Write-Host " Version Tag: $Version" -ForegroundColor Yellow
Write-Host " Target Registry: $Registry" -ForegroundColor Yellow
Write-Host "================================================================================"

# Get Git commit hash if in a repo
$CommitHash = "local"
try {
    $CommitHash = (git rev-parse --short HEAD 2>$null)
    if (-not $CommitHash) { $CommitHash = "local" }
} catch {
    $CommitHash = "local"
}
Write-Host "[+] Git Commit Reference: $CommitHash" -ForegroundColor Gray

# Define components
$Components = @(
    @{ Name = "modelforge/backend"; Context = "$WorkspaceRoot/backend"; Dockerfile = "$WorkspaceRoot/backend/Dockerfile" },
    @{ Name = "modelforge/inference"; Context = "$WorkspaceRoot/inference_service"; Dockerfile = "$WorkspaceRoot/inference_service/Dockerfile" },
    @{ Name = "modelforge/frontend"; Context = "$WorkspaceRoot/frontend"; Dockerfile = "$WorkspaceRoot/frontend/Dockerfile" }
)

foreach ($comp in $Components) {
    Write-Host "`n--------------------------------------------------------------------------------" -ForegroundColor DarkCyan
    Write-Host " Building Image: $($comp.Name)" -ForegroundColor Green
    Write-Host " Context: $($comp.Context)" -ForegroundColor Gray
    Write-Host "--------------------------------------------------------------------------------"

    $Tags = @(
        "$($comp.Name):$Version",
        "$($comp.Name):v$Version",
        "$($comp.Name):$CommitHash",
        "$($comp.Name):latest",
        "$Registry/$($comp.Name):$Version",
        "$Registry/$($comp.Name):v$Version",
        "$Registry/$($comp.Name):v1",
        "$Registry/$($comp.Name):latest"
    )

    $TagArgs = @()
    foreach ($t in $Tags) {
        $TagArgs += @("-t", $t)
    }

    # Build image
    $buildCmd = @("build") + $TagArgs + @("-f", $comp.Dockerfile, $comp.Context)
    & docker @buildCmd
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to build image: $($comp.Name)"
    }
    Write-Host "[OK] Built $($comp.Name) with tags: $($Tags -join ', ')" -ForegroundColor Green

    # Push to local registry
    if (-not $SkipPush) {
        Write-Host "[+] Pushing to local registry: $Registry/$($comp.Name)..." -ForegroundColor Yellow
        & docker push "$Registry/$($comp.Name):$Version"
        & docker push "$Registry/$($comp.Name):v1"
        & docker push "$Registry/$($comp.Name):latest"
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Could not push to $Registry. Verifying registry container..."
        } else {
            Write-Host "[OK] Pushed $($comp.Name) to $Registry" -ForegroundColor Green
        }
    }
}

Write-Host "`n================================================================================" -ForegroundColor Cyan
Write-Host " DOCKER BUILD & REGISTRY PIPELINE COMPLETED SUCCESSFULLY" -ForegroundColor Green
Write-Host "================================================================================"
