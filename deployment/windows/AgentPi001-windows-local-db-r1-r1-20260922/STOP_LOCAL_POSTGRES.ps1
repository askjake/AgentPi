param([string]$Root = "")
$ErrorActionPreference = "Continue"
if ([string]::IsNullOrWhiteSpace($Root)) { $Root = Split-Path -Parent $PSScriptRoot }
$Root = (Resolve-Path $Root).Path
$Run = Join-Path $Root "runtime"
$VersionFile = Join-Path $Run "postgresql-version.txt"
if (-not (Test-Path $VersionFile)) { Write-Host "No local PostgreSQL version marker; nothing to stop."; exit 0 }
$Version = (Get-Content $VersionFile | Select-Object -First 1).Trim()
$PgCtl = Join-Path $Run "postgresql-$Version\pgsql\bin\pg_ctl.exe"
$Data = Join-Path $Run "postgres-data"
if ((Test-Path $PgCtl) -and (Test-Path (Join-Path $Data "PG_VERSION"))) {
    & $PgCtl status -D $Data *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Stopping local PostgreSQL..."
        & $PgCtl -D $Data -w stop -m fast
    } else {
        Write-Host "Local PostgreSQL is already stopped."
    }
}
