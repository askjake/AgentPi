param([string]$Root = "")
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
if ([string]::IsNullOrWhiteSpace($Root)) { $Root = Split-Path -Parent $PSScriptRoot }
$Root = (Resolve-Path $Root).Path
$Run = Join-Path $Root "runtime"
$EnvFile = Join-Path $Run "local-db.env"
$VersionFile = Join-Path $Run "postgresql-version.txt"
if (-not (Test-Path $EnvFile)) { throw "Local DB is not initialized; run SETUP_LOCAL_POSTGRES.ps1 first." }
if (-not (Test-Path $VersionFile)) { throw "PostgreSQL version marker missing." }
$Version = (Get-Content $VersionFile | Select-Object -First 1).Trim()
$PgRoot = Join-Path $Run "postgresql-$Version\pgsql"
$PgCtl = Join-Path $PgRoot "bin\pg_ctl.exe"
$PgReady = Join-Path $PgRoot "bin\pg_isready.exe"
$Data = Join-Path $Run "postgres-data"
$LogDir = Join-Path $Run "logs"
$Log = Join-Path $LogDir "postgresql.log"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
if (-not (Test-Path $PgCtl)) { throw "pg_ctl.exe missing: $PgCtl" }
if (-not (Test-Path (Join-Path $Data "PG_VERSION"))) { throw "PostgreSQL data directory is not initialized: $Data" }

& $PgCtl status -D $Data *> $null
if ($LASTEXITCODE -eq 0) {
    Write-Host "Local PostgreSQL already running on 127.0.0.1:55432"
    exit 0
}

& $PgCtl -D $Data -l $Log -w start
if ($LASTEXITCODE -ne 0) { throw "Local PostgreSQL failed to start. See $Log" }
& $PgReady -h 127.0.0.1 -p 55432
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL started but is not ready on 127.0.0.1:55432" }
Write-Host "LOCAL POSTGRESQL RUNNING: 127.0.0.1:55432"
