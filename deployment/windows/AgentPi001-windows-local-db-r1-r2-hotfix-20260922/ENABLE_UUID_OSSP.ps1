param([string]$Root = "")
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
if ([string]::IsNullOrWhiteSpace($Root)) { $Root = Split-Path -Parent $PSScriptRoot }
$Root = (Resolve-Path $Root).Path
$Run = Join-Path $Root "runtime"
$AdminEnv = Join-Path $Run "local-db-admin.env"
$VersionFile = Join-Path $Run "postgresql-version.txt"
if (-not (Test-Path $AdminEnv)) { throw "Missing local DB admin credential file: $AdminEnv" }
if (-not (Test-Path $VersionFile)) { throw "Missing PostgreSQL version marker: $VersionFile" }
$Version = (Get-Content -LiteralPath $VersionFile | Select-Object -First 1).Trim()
$Psql = Join-Path $Run "postgresql-$Version\pgsql\bin\psql.exe"
if (-not (Test-Path $Psql)) { throw "psql.exe missing: $Psql" }
$admin = @{}
foreach ($line in Get-Content -LiteralPath $AdminEnv) {
    if ([string]::IsNullOrWhiteSpace($line) -or $line.TrimStart().StartsWith('#')) { continue }
    $parts = $line.Split('=',2)
    if ($parts.Count -eq 2) { $admin[$parts[0]] = $parts[1] }
}
if (-not $admin.ContainsKey('POSTGRES_ADMIN_USER') -or -not $admin.ContainsKey('POSTGRES_ADMIN_PWD')) {
    throw "local-db-admin.env is incomplete"
}
$sqlFile = Join-Path $Run "enable-uuid-ossp.sql"
Set-Content -LiteralPath $sqlFile -Value 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp";' -Encoding ASCII
$env:PGPASSWORD = $admin['POSTGRES_ADMIN_PWD']
try {
    & $Psql -h 127.0.0.1 -p 55432 -U $admin['POSTGRES_ADMIN_USER'] -d dishchat_local -v ON_ERROR_STOP=1 -f $sqlFile
    if ($LASTEXITCODE -ne 0) { throw "CREATE EXTENSION uuid-ossp failed" }
    & $Psql -h 127.0.0.1 -p 55432 -U $admin['POSTGRES_ADMIN_USER'] -d dishchat_local -v ON_ERROR_STOP=1 -Atc 'SELECT extname FROM pg_extension WHERE extname = ''uuid-ossp'';'
    if ($LASTEXITCODE -ne 0) { throw "uuid-ossp verification query failed" }
} finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $sqlFile -Force -ErrorAction SilentlyContinue
}
Write-Host "UUID_OSSP READY"
