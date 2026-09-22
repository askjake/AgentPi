param(
    [string]$Branch = "feature/agentpi-initial",
    [switch]$SkipTests
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "lib.ps1")
$Root = Get-AgentPiRepoRoot
$Run = Join-Path $Root "runtime"
Ensure-Directory $Run

Push-Location $Root
try {
    $dirty = (& git status --porcelain --untracked-files=no)
    if ($dirty) {
        Write-Host $dirty
        throw "Tracked working tree changes detected. Commit/stash/reconcile before update."
    }

    & (Join-Path $PSScriptRoot "backup-db.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Database backup failed." }

    $oldSha = (& git rev-parse HEAD).Trim()
    Set-Content -LiteralPath (Join-Path $Run "pre-update-git-sha.txt") -Value $oldSha -Encoding ASCII

    & (Join-Path $PSScriptRoot "stop.ps1")

    & git fetch origin $Branch
    if ($LASTEXITCODE -ne 0) { throw "git fetch failed." }
    & git switch $Branch
    if ($LASTEXITCODE -ne 0) { throw "git switch failed." }
    & git merge --ff-only "origin/$Branch"
    if ($LASTEXITCODE -ne 0) { throw "Fast-forward update failed." }

    if ($SkipTests) {
        & (Join-Path $PSScriptRoot "install.ps1") -NonInteractive -NoStart -SkipTests
    } else {
        & (Join-Path $PSScriptRoot "install.ps1") -NonInteractive -NoStart
    }
    if ($LASTEXITCODE -ne 0) { throw "Install/migration stage failed." }

    & (Join-Path $PSScriptRoot "start.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Restart failed." }

    & (Join-Path $PSScriptRoot "verify.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Post-update verification failed." }

    Write-Host "PREVIOUS_SHA=$oldSha"
    Write-Host ("CURRENT_SHA=" + (& git rev-parse HEAD).Trim())
    Write-Host "AGENTPI001 WINDOWS UPDATE PASS"
} finally { Pop-Location }
