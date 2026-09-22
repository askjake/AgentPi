param(
    [string]$Root = "",
    [string]$PostgresBuild = "17.11-4",
    [string]$DownloadUrl = "https://get.enterprisedb.com/postgresql/postgresql-17.11-4-windows-x64-binaries.zip"
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
if ([string]::IsNullOrWhiteSpace($Root)) { $Root = Split-Path -Parent $PSScriptRoot }
$Root = (Resolve-Path $Root).Path
$Run = Join-Path $Root "runtime"
$Logs = Join-Path $Run "logs"
$PgHome = Join-Path $Run "postgresql-$PostgresBuild"
$PgRoot = Join-Path $PgHome "pgsql"
$PgBin = Join-Path $PgRoot "bin"
$Zip = Join-Path $Run "postgresql-$PostgresBuild-windows-x64-binaries.zip"
$Data = Join-Path $Run "postgres-data"
$EnvFile = Join-Path $Run "local-db.env"
$AdminEnv = Join-Path $Run "local-db-admin.env"
$VersionFile = Join-Path $Run "postgresql-version.txt"
New-Item -ItemType Directory -Force -Path $Run,$Logs | Out-Null

# Retire the prior Pi DB tunnel if this bundle started it. We will own 55432 locally.
$TunnelPidFile = Join-Path $Run "db-tunnel.pid"
if (Test-Path $TunnelPidFile) {
    $pidValue = Get-Content $TunnelPidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pidValue -and (Get-Process -Id $pidValue -ErrorAction SilentlyContinue)) {
        Write-Host "Stopping prior PostgreSQL SSH tunnel PID $pidValue..."
        taskkill.exe /PID $pidValue /T /F 2>$null | Out-Null
    }
    Remove-Item $TunnelPidFile -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500
}

if (-not (Test-Path (Join-Path $PgBin "initdb.exe"))) {
    if (-not (Test-Path $Zip)) {
        Write-Host "Downloading PostgreSQL $PostgresBuild portable binaries from EDB..."
        Invoke-WebRequest -UseBasicParsing -Uri $DownloadUrl -OutFile $Zip
    }
    if (Test-Path $PgHome) { Remove-Item -Recurse -Force $PgHome }
    New-Item -ItemType Directory -Force -Path $PgHome | Out-Null
    Write-Host "Extracting PostgreSQL binaries..."
    Expand-Archive -LiteralPath $Zip -DestinationPath $PgHome -Force
}
foreach ($exe in @("initdb.exe","pg_ctl.exe","pg_isready.exe","psql.exe","createdb.exe")) {
    if (-not (Test-Path (Join-Path $PgBin $exe))) { throw "Portable PostgreSQL archive missing $exe" }
}
Set-Content -LiteralPath $VersionFile -Value $PostgresBuild -Encoding ASCII

function New-HexSecret([int]$Bytes=24) {
    $buffer = New-Object byte[] $Bytes
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($buffer) } finally { $rng.Dispose() }
    return ([BitConverter]::ToString($buffer)).Replace('-','').ToLowerInvariant()
}

if (-not (Test-Path (Join-Path $Data "PG_VERSION"))) {
    Write-Host "Initializing private PostgreSQL cluster under runtime\postgres-data..."
    if (Test-Path $Data) { Remove-Item -Recurse -Force $Data }
    $adminUser = "postgres"
    $appUser = "agentpi_local"
    $dbName = "dishchat_local"
    $adminPw = New-HexSecret
    $appPw = New-HexSecret
    $pwFile = Join-Path $Run ".postgres-init-pw"
    Set-Content -LiteralPath $pwFile -Value $adminPw -NoNewline -Encoding ASCII
    try {
        & (Join-Path $PgBin "initdb.exe") -D $Data -U $adminUser -E UTF8 --locale=C --auth-host=scram-sha-256 --auth-local=scram-sha-256 "--pwfile=$pwFile"
        if ($LASTEXITCODE -ne 0) { throw "initdb failed" }
    } finally { Remove-Item $pwFile -Force -ErrorAction SilentlyContinue }

    Add-Content -LiteralPath (Join-Path $Data "postgresql.conf") -Value @"

# AgentPi001 Windows local database
listen_addresses = '127.0.0.1'
port = 55432
password_encryption = 'scram-sha-256'
max_connections = 100
"@

    @(
        "POSTGRES_HOST=127.0.0.1",
        "POSTGRES_PORT=55432",
        "POSTGRES_DB=$dbName",
        "POSTGRES_USER=$appUser",
        "POSTGRES_PWD=$appPw"
    ) | Set-Content -LiteralPath $EnvFile -Encoding ASCII
    @(
        "POSTGRES_ADMIN_USER=$adminUser",
        "POSTGRES_ADMIN_PWD=$adminPw"
    ) | Set-Content -LiteralPath $AdminEnv -Encoding ASCII

    & (Join-Path $PSScriptRoot "START_LOCAL_POSTGRES.ps1") -Root $Root
    if ($LASTEXITCODE -ne 0) { throw "Local PostgreSQL startup failed" }

    $env:PGPASSWORD = $adminPw
    try {
        $createRole = "CREATE ROLE $appUser LOGIN PASSWORD '$appPw';"
        & (Join-Path $PgBin "psql.exe") -h 127.0.0.1 -p 55432 -U $adminUser -d postgres -v ON_ERROR_STOP=1 -c $createRole
        if ($LASTEXITCODE -ne 0) { throw "Failed to create application role" }
        & (Join-Path $PgBin "createdb.exe") -h 127.0.0.1 -p 55432 -U $adminUser -O $appUser $dbName
        if ($LASTEXITCODE -ne 0) { throw "Failed to create application database" }
    } finally { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue }
    Write-Host "Fresh local database created: $dbName (credentials stored only in runtime\local-db.env)"
} else {
    if (-not (Test-Path $EnvFile)) { throw "Existing data directory has no local-db.env; refusing to guess credentials." }
    Write-Host "Existing local PostgreSQL data directory found; preserving it."
    & (Join-Path $PSScriptRoot "START_LOCAL_POSTGRES.ps1") -Root $Root
}

& (Join-Path $PSScriptRoot "MIGRATE_LOCAL_DB.ps1") -Root $Root
if ($LASTEXITCODE -ne 0) { throw "Local database migrations failed" }
Write-Host "============================================================"
Write-Host "LOCAL POSTGRESQL SETUP PASS"
Write-Host "Endpoint: 127.0.0.1:55432"
Write-Host "Data:     $Data"
Write-Host "Secrets:  $EnvFile"
Write-Host "============================================================"
