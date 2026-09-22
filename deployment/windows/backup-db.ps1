param([string]$OutputPath = "")
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "lib.ps1")
$Root = Get-AgentPiRepoRoot
Start-AgentPiPostgres $Root
$pg = Get-PgPaths $Root
$db = Read-DotEnv $pg.Env
$backupDir = Join-Path $Root "runtime\backups"
Ensure-Directory $backupDir
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
    $OutputPath = Join-Path $backupDir "dishchat-$stamp.dump"
}
$env:PGPASSWORD = $db["POSTGRES_PWD"]
try {
    & (Join-Path $pg.Bin "pg_dump.exe") -h $db["POSTGRES_HOST"] -p $db["POSTGRES_PORT"] -U $db["POSTGRES_USER"] -d $db["POSTGRES_DB"] -Fc -f $OutputPath
    if ($LASTEXITCODE -ne 0) { throw "pg_dump failed." }
} finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
}
if (-not (Test-Path $OutputPath) -or (Get-Item $OutputPath).Length -eq 0) { throw "Backup was not created." }
Write-Host "DB_BACKUP=$OutputPath"
