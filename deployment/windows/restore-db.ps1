param(
    [Parameter(Mandatory=$true)][string]$BackupPath,
    [switch]$Force
)
$ErrorActionPreference = "Stop"
if (-not $Force) { throw "restore-db.ps1 is destructive. Re-run with -Force." }
. (Join-Path $PSScriptRoot "lib.ps1")
$Root = Get-AgentPiRepoRoot
if (-not (Test-Path $BackupPath)) { throw "Backup not found: $BackupPath" }
Start-AgentPiPostgres $Root
$pg = Get-PgPaths $Root
$db = Read-DotEnv $pg.Env
$admin = Read-DotEnv $pg.AdminEnv

$env:PGPASSWORD = $admin["POSTGRES_ADMIN_PWD"]
try {
    & (Join-Path $pg.Bin "dropdb.exe") -h 127.0.0.1 -p 55432 -U $admin["POSTGRES_ADMIN_USER"] --force $db["POSTGRES_DB"]
    if ($LASTEXITCODE -ne 0) { throw "dropdb failed." }
    & (Join-Path $pg.Bin "createdb.exe") -h 127.0.0.1 -p 55432 -U $admin["POSTGRES_ADMIN_USER"] -O $db["POSTGRES_USER"] $db["POSTGRES_DB"]
    if ($LASTEXITCODE -ne 0) { throw "createdb failed." }
    & (Join-Path $pg.Bin "psql.exe") -h 127.0.0.1 -p 55432 -U $admin["POSTGRES_ADMIN_USER"] -d $db["POSTGRES_DB"] -v ON_ERROR_STOP=1 -c 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp";'
    if ($LASTEXITCODE -ne 0) { throw "uuid-ossp recreation failed." }
} finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
}

$env:PGPASSWORD = $db["POSTGRES_PWD"]
try {
    & (Join-Path $pg.Bin "pg_restore.exe") -h 127.0.0.1 -p 55432 -U $db["POSTGRES_USER"] -d $db["POSTGRES_DB"] --no-owner $BackupPath
    if ($LASTEXITCODE -ne 0) { throw "pg_restore failed." }
} finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
}
Write-Host "DB RESTORE PASS"
