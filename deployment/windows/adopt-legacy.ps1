param(
    [Parameter(Mandatory=$true)][string]$LegacyRoot,
    [switch]$SkipTests
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "lib.ps1")
$Root = Get-AgentPiRepoRoot
$LegacyRoot = (Resolve-Path $LegacyRoot).Path

if ($LegacyRoot -eq $Root) { throw "LegacyRoot must be a different installation." }
$legacyBackend = Join-Path $LegacyRoot "dish-chat\backend"
$legacyEnv = Join-Path $legacyBackend ".env"
$legacyRun = Join-Path $LegacyRoot "runtime"
if (-not (Test-Path $legacyEnv)) { throw "Legacy backend .env not found: $legacyEnv" }
if (-not (Test-Path (Join-Path $legacyRun "local-db.env"))) { throw "Legacy local DB state not found under $legacyRun" }

$newRun = Join-Path $Root "runtime"
if ((Test-Path (Join-Path $newRun "postgres-data\PG_VERSION")) -or (Test-Path (Join-Path $Root "dish-chat\backend\.env"))) {
    throw "New repo already contains runtime/database configuration. Refusing to overwrite it."
}

# Stop legacy application PID-managed processes.
foreach ($name in @("dishchat-frontend","dishchat-backend","agentpi")) {
    $pidFile = Join-Path $legacyRun "$name.pid"
    if (Test-Path $pidFile) {
        $pidValue = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($pidValue -and (Get-Process -Id $pidValue -ErrorAction SilentlyContinue)) {
            Write-Host "Stopping legacy $name PID $pidValue"
            taskkill.exe /PID $pidValue /T /F 2>$null | Out-Null
        }
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }
}

# Cleanly stop the legacy portable database before copying it.
$legacyVersionFile = Join-Path $legacyRun "postgresql-version.txt"
if (Test-Path $legacyVersionFile) {
    $legacyVersion = (Get-Content $legacyVersionFile | Select-Object -First 1).Trim()
    $legacyCtl = Join-Path $legacyRun "postgresql-$legacyVersion\pgsql\bin\pg_ctl.exe"
    $legacyData = Join-Path $legacyRun "postgres-data"
    if ((Test-Path $legacyCtl) -and (Test-Path (Join-Path $legacyData "PG_VERSION"))) {
        & $legacyCtl status -D $legacyData *> $null
        if ($LASTEXITCODE -eq 0) {
            & $legacyCtl -D $legacyData -w stop -m fast
            if ($LASTEXITCODE -ne 0) { throw "Legacy PostgreSQL failed to stop cleanly." }
        }
    }
}

Write-Host "Copying legacy runtime database state into repo-native installation..."
New-Item -ItemType Directory -Force -Path $newRun | Out-Null
& robocopy.exe $legacyRun $newRun /E /COPY:DAT /DCOPY:DAT /R:1 /W:1 /XD logs workspaces /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Legacy runtime copy failed with robocopy exit $LASTEXITCODE" }

New-Item -ItemType Directory -Force -Path (Join-Path $Root "dish-chat\backend") | Out-Null
Copy-Item -LiteralPath $legacyEnv -Destination (Join-Path $Root "dish-chat\backend\.env") -Force
foreach ($relative in @("dish-chat\.env","dish-chat\backend\app\.env","dish-chat\backend\.env.local")) {
    $src = Join-Path $LegacyRoot $relative
    if (Test-Path $src) {
        $dst = Join-Path $Root $relative
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
        Copy-Item -LiteralPath $src -Destination $dst -Force
    }
}

if ($SkipTests) {
    & (Join-Path $PSScriptRoot "install.ps1") -NonInteractive -NoStart -SkipTests
} else {
    & (Join-Path $PSScriptRoot "install.ps1") -NonInteractive -NoStart
}
if ($LASTEXITCODE -ne 0) { throw "Repo-native installation/migration failed." }

& (Join-Path $PSScriptRoot "start.ps1")
if ($LASTEXITCODE -ne 0) { throw "Repo-native start failed." }
& (Join-Path $PSScriptRoot "verify.ps1")
if ($LASTEXITCODE -ne 0) { throw "Repo-native verification failed." }

Write-Host "LEGACY_ROOT=$LegacyRoot"
Write-Host "NEW_ROOT=$Root"
Write-Host "Legacy tree was preserved; remove it only after validating the new installation."
Write-Host "AGENTPI001 WINDOWS LEGACY ADOPTION PASS"
