param(
    [string]$CoverityAssistToken = "",
    [string]$DefaultUserEmail = "local@localhost",
    [string]$PostgresBuild = "17.11-4",
    [switch]$NonInteractive,
    [switch]$ResetCoverityAssistToken,
    [switch]$SkipTests,
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "lib.ps1")

$Root = Get-AgentPiRepoRoot
$Run = Join-Path $Root "runtime"
$Logs = Join-Path $Run "logs"
$Backend = Join-Path $Root "dish-chat\backend"
$BackendEnv = Join-Path $Backend ".env"
$AgentVenv = Join-Path $Root ".venv-windows"
$DishVenv = Join-Path $Backend ".venv-windows"

Ensure-Directory $Run
Ensure-Directory $Logs
Ensure-Directory (Join-Path $Run "workspaces")

if (-not (Test-Path (Join-Path $Root ".git"))) { throw "Run this installer from a Git clone of AgentPi." }

$Python = Resolve-Python313
Write-Host "Python: $Python"

# Exact tested dependency freezes.
$agentFreeze = Join-Path $Root "deployment\evidence\requirements-agentpi-windows-freeze.txt"
$dishFreeze = Join-Path $Root "deployment\evidence\requirements-dishchat-windows-freeze.txt"
if (-not (Test-Path $agentFreeze) -or -not (Test-Path $dishFreeze)) {
    throw "Deployment dependency evidence is missing."
}
$utf8NoBom = [Text.UTF8Encoding]::new($false)
$agentReq = Join-Path $Run "requirements-agentpi-windows.txt"
$dishReq = Join-Path $Run "requirements-dishchat-windows.txt"
[IO.File]::WriteAllText($agentReq, [IO.File]::ReadAllText($agentFreeze).Replace("`r`n","`n"), $utf8NoBom)
[IO.File]::WriteAllText($dishReq, [IO.File]::ReadAllText($dishFreeze).Replace("`r`n","`n"), $utf8NoBom)

if (-not (Test-Path $AgentVenv)) { & $Python -m venv $AgentVenv }
$AgentPy = Join-Path $AgentVenv "Scripts\python.exe"
& $AgentPy -m pip install --upgrade pip setuptools wheel
& $AgentPy -m pip install -r $agentReq
& $AgentPy -m pip check
if ($LASTEXITCODE -ne 0) { throw "AgentPi dependency setup failed." }

if (-not (Test-Path $DishVenv)) { & $Python -m venv $DishVenv }
$DishPy = Join-Path $DishVenv "Scripts\python.exe"
& $DishPy -m pip install --upgrade pip setuptools wheel
& $DishPy -m pip install -r $dishReq
& $DishPy -m pip check
if ($LASTEXITCODE -ne 0) { throw "DishChat dependency setup failed." }

# Runtime application environment. Never overwrite an existing secret unless explicitly supplied.
if (-not (Test-Path $BackendEnv)) {
    [IO.File]::WriteAllText($BackendEnv, "", $utf8NoBom)
}
$currentEnv = Read-DotEnv $BackendEnv

if ($ResetCoverityAssistToken) {
    # Explicitly ignore an existing .env value. Prefer an explicitly supplied
    # parameter, then a process environment value, otherwise prompt securely.
    if ([string]::IsNullOrWhiteSpace($CoverityAssistToken)) {
        if ($env:COVERITY_ASSIST_TOKEN) {
            $CoverityAssistToken = $env:COVERITY_ASSIST_TOKEN
        } elseif (-not $NonInteractive) {
            $secure = Read-Host "New Coverity Assist token" -AsSecureString
            $CoverityAssistToken = [Net.NetworkCredential]::new("", $secure).Password
        } else {
            throw "Reset requested but no COVERITY_ASSIST_TOKEN was supplied."
        }
    }
} elseif ([string]::IsNullOrWhiteSpace($CoverityAssistToken)) {
    if ($currentEnv.ContainsKey("COVERITY_ASSIST_TOKEN") -and $currentEnv["COVERITY_ASSIST_TOKEN"]) {
        $CoverityAssistToken = $currentEnv["COVERITY_ASSIST_TOKEN"]
    } elseif ($env:COVERITY_ASSIST_TOKEN) {
        $CoverityAssistToken = $env:COVERITY_ASSIST_TOKEN
    } elseif (-not $NonInteractive) {
        $secure = Read-Host "Coverity Assist token" -AsSecureString
        $CoverityAssistToken = [Net.NetworkCredential]::new("", $secure).Password
    } else {
        throw "COVERITY_ASSIST_TOKEN is required for non-interactive installation."
    }
}

Set-DotEnvValue $BackendEnv "AUTH_DISABLED" "true" -OnlyIfMissing
Set-DotEnvValue $BackendEnv "LOCAL" "true" -OnlyIfMissing
Set-DotEnvValue $BackendEnv "DEBUG" "false" -OnlyIfMissing
Set-DotEnvValue $BackendEnv "DEFAULT_USER_EMAIL" $DefaultUserEmail -OnlyIfMissing
Set-DotEnvValue $BackendEnv "PLLM_PROVIDER" "coverity-assist" -OnlyIfMissing
Set-DotEnvValue $BackendEnv "ELLM_PROVIDER" "coverity-assist" -OnlyIfMissing
Set-DotEnvValue $BackendEnv "COVERITY_ASSIST_URL" "https://coverity-assist-stg.dishtv.technology/chat" -OnlyIfMissing
Set-DotEnvValue $BackendEnv "COVERITY_ASSIST_TOKEN" $CoverityAssistToken
Set-DotEnvValue $BackendEnv "COVERITY_ASSIST_VERIFY_SSL" "false" -OnlyIfMissing
Set-DotEnvValue $BackendEnv "DEFAULT_MODEL_PREFERENCE" "reasoning" -OnlyIfMissing
Set-DotEnvValue $BackendEnv "ENABLE_TOOL_CALLS" "true" -OnlyIfMissing
Set-DotEnvValue $BackendEnv "MAX_TOOL_ITERATIONS" "100" -OnlyIfMissing
Set-DotEnvValue $BackendEnv "TOOL_CALL_TIMEOUT" "12000" -OnlyIfMissing
Set-DotEnvValue $BackendEnv "ENABLE_BETAREPORT_MCP" "false" -OnlyIfMissing
Set-DotEnvValue $BackendEnv "ENABLE_VIEWERSHIP_MCP" "false" -OnlyIfMissing
Set-DotEnvValue $BackendEnv "ENABLE_LOG_ASSIST_MCP" "false" -OnlyIfMissing
Set-DotEnvValue $BackendEnv "ENABLE_INTERNAL_TOOLS_MCP" "false" -OnlyIfMissing
$currentEnv = Read-DotEnv $BackendEnv
if (-not $currentEnv.ContainsKey("MASTER_KEY") -or -not $currentEnv["MASTER_KEY"]) {
    Set-DotEnvValue $BackendEnv "MASTER_KEY" (New-MasterKey)
}

# Portable PostgreSQL.
$PgHome = Join-Path $Run "postgresql-$PostgresBuild"
$PgBin = Join-Path $PgHome "pgsql\bin"
$PgZip = Join-Path $Run "postgresql-$PostgresBuild-windows-x64-binaries.zip"
$Data = Join-Path $Run "postgres-data"
$LocalDbEnv = Join-Path $Run "local-db.env"
$AdminEnv = Join-Path $Run "local-db-admin.env"
$VersionFile = Join-Path $Run "postgresql-version.txt"

function Test-PortablePostgresPayload {
    $required = @(
        (Join-Path $PgBin "initdb.exe"),
        (Join-Path $PgBin "pg_ctl.exe"),
        (Join-Path $PgBin "pg_isready.exe"),
        (Join-Path $PgBin "psql.exe"),
        (Join-Path $PgBin "createdb.exe"),
        (Join-Path $PgBin "dropdb.exe"),
        (Join-Path $PgBin "pg_dump.exe"),
        (Join-Path $PgBin "pg_restore.exe"),
        (Join-Path $PgHome "pgsql\share\postgres.bki")
    )
    foreach ($path in $required) {
        if (-not (Test-Path $path)) { return $false }
    }
    return $true
}

function Download-PostgresArchive {
    param([string]$Url,[string]$Destination)

    Remove-Item -LiteralPath $Destination -Force -ErrorAction SilentlyContinue

    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl -and $curl.Source) {
        Write-Host "Downloading PostgreSQL with curl retry support..."
        & $curl.Source -fL --retry 4 --retry-delay 2 --retry-all-errors -o $Destination $Url
        if ($LASTEXITCODE -eq 0 -and (Test-Path $Destination) -and (Get-Item $Destination).Length -gt 1MB) {
            return
        }
        Remove-Item -LiteralPath $Destination -Force -ErrorAction SilentlyContinue
    }

    Write-Host "Downloading PostgreSQL with Invoke-WebRequest..."
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Destination
    if (-not (Test-Path $Destination) -or (Get-Item $Destination).Length -le 1MB) {
        throw "PostgreSQL archive download is missing or unexpectedly small."
    }
}

function Expand-PostgresRuntime {
    param([string]$Archive,[string]$Destination)

    # The EDB binary ZIP also contains pgAdmin, including a large embedded Python
    # ZIP that is unnecessary for AgentPi. Some Windows/libarchive combinations
    # fail while expanding that entry. Extract the PostgreSQL runtime with
    # Python's zipfile module and deliberately skip pgAdmin/StackBuilder.
    $extractor = Join-Path $Run "extract-postgresql-runtime.py"
    $code = @'
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

archive = Path(sys.argv[1])
destination = Path(sys.argv[2])

skip_prefixes = (
    "pgsql/pgAdmin 4/",
    "pgsql/StackBuilder/",
)

required = (
    "pgsql/bin/initdb.exe",
    "pgsql/bin/pg_ctl.exe",
    "pgsql/bin/psql.exe",
    "pgsql/bin/pg_dump.exe",
    "pgsql/bin/pg_restore.exe",
    "pgsql/share/postgres.bki",
)

seen = set()
count = 0

with zipfile.ZipFile(archive, "r") as zf:
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if any(name.startswith(prefix) for prefix in skip_prefixes):
            continue
        zf.extract(info, destination)
        seen.add(name.rstrip("/"))
        count += 1

missing = [name for name in required if not (destination / name).is_file()]
if missing:
    raise SystemExit("required PostgreSQL files missing after extraction: " + ", ".join(missing))

print(f"POSTGRES_RUNTIME_EXTRACTED_FILES={count}")
'@
    [IO.File]::WriteAllText($extractor, $code, [Text.UTF8Encoding]::new($false))
    try {
        & $Python $extractor $Archive $Destination
        return ($LASTEXITCODE -eq 0)
    } finally {
        Remove-Item -LiteralPath $extractor -Force -ErrorAction SilentlyContinue
    }
}

if (-not (Test-PortablePostgresPayload)) {
    if (Test-Path $PgHome) {
        Write-Warning "Incomplete PostgreSQL runtime detected; removing partial extraction."
        Remove-Item -Recurse -Force $PgHome
    }

    $url = "https://get.enterprisedb.com/postgresql/postgresql-$PostgresBuild-windows-x64-binaries.zip"
    $installed = $false

    for ($attempt = 1; $attempt -le 3 -and -not $installed; $attempt++) {
        Write-Host "PostgreSQL runtime bootstrap attempt $attempt of 3..."

        if (-not (Test-Path $PgZip) -or $attempt -gt 1) {
            Download-PostgresArchive -Url $url -Destination $PgZip
        }

        if (Test-Path $PgHome) { Remove-Item -Recurse -Force $PgHome }
        Ensure-Directory $PgHome

        try {
            $expanded = Expand-PostgresRuntime -Archive $PgZip -Destination $PgHome
            $installed = $expanded -and (Test-PortablePostgresPayload)
        } catch {
            Write-Warning ("PostgreSQL extraction attempt failed: " + $_.Exception.Message)
            $installed = $false
        }

        if (-not $installed) {
            Remove-Item -Recurse -Force $PgHome -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath $PgZip -Force -ErrorAction SilentlyContinue
        }
    }

    if (-not $installed) {
        throw "Unable to obtain a complete portable PostgreSQL runtime after 3 attempts."
    }
}

foreach ($exe in @("initdb.exe","pg_ctl.exe","pg_isready.exe","psql.exe","createdb.exe","dropdb.exe","pg_dump.exe","pg_restore.exe")) {
    if (-not (Test-Path (Join-Path $PgBin $exe))) { throw "Portable PostgreSQL missing $exe" }
}
if (-not (Test-Path (Join-Path $PgHome "pgsql\share\postgres.bki"))) {
    throw "Portable PostgreSQL is incomplete: pgsql\share\postgres.bki is missing."
}
Set-Content -LiteralPath $VersionFile -Value $PostgresBuild -Encoding ASCII

if (-not (Test-Path (Join-Path $Data "PG_VERSION"))) {
    $adminUser = "postgres"
    $appUser = "agentpi_local"
    $dbName = "dishchat_local"
    $adminPw = New-HexSecret
    $appPw = New-HexSecret
    $pwFile = Join-Path $Run ".postgres-init-pw"
    Set-Content -LiteralPath $pwFile -Value $adminPw -NoNewline -Encoding ASCII
    try {
        & (Join-Path $PgBin "initdb.exe") -D $Data -U $adminUser -E UTF8 --locale=C --auth-host=scram-sha-256 --auth-local=scram-sha-256 "--pwfile=$pwFile"
        if ($LASTEXITCODE -ne 0) { throw "initdb failed." }
    } finally {
        Remove-Item $pwFile -Force -ErrorAction SilentlyContinue
    }
    Add-Content -LiteralPath (Join-Path $Data "postgresql.conf") -Value @"

# AgentPi001 portable database
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
    ) | Set-Content -LiteralPath $LocalDbEnv -Encoding ASCII
    @(
        "POSTGRES_ADMIN_USER=$adminUser",
        "POSTGRES_ADMIN_PWD=$adminPw"
    ) | Set-Content -LiteralPath $AdminEnv -Encoding ASCII

    Start-AgentPiPostgres $Root

    $env:PGPASSWORD = $adminPw
    try {
        & (Join-Path $PgBin "psql.exe") -h 127.0.0.1 -p 55432 -U $adminUser -d postgres -v ON_ERROR_STOP=1 -c "CREATE ROLE $appUser LOGIN PASSWORD '$appPw';"
        if ($LASTEXITCODE -ne 0) { throw "Application role creation failed." }
        & (Join-Path $PgBin "createdb.exe") -h 127.0.0.1 -p 55432 -U $adminUser -O $appUser $dbName
        if ($LASTEXITCODE -ne 0) { throw "Application database creation failed." }
    } finally {
        Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    }
} else {
    if (-not (Test-Path $LocalDbEnv) -or -not (Test-Path $AdminEnv)) {
        throw "Existing PostgreSQL data directory is missing runtime credential files."
    }
    Start-AgentPiPostgres $Root
}

# Required before the Journal migration.
# Use a temporary SQL file instead of psql -c so native-command argument
# parsing on Windows cannot remove the quotes around the hyphenated extension.
$admin = Read-DotEnv $AdminEnv
$db = Read-DotEnv $LocalDbEnv
$uuidSql = Join-Path $Run "enable-uuid-ossp.sql"
[IO.File]::WriteAllText(
    $uuidSql,
    'CREATE EXTENSION IF NOT EXISTS "uuid-ossp";' + [Environment]::NewLine,
    [Text.Encoding]::ASCII
)
$env:PGPASSWORD = $admin["POSTGRES_ADMIN_PWD"]
try {
    & (Join-Path $PgBin "psql.exe") -h 127.0.0.1 -p 55432 -U $admin["POSTGRES_ADMIN_USER"] -d $db["POSTGRES_DB"] -v ON_ERROR_STOP=1 -f $uuidSql
    if ($LASTEXITCODE -ne 0) { throw "uuid-ossp setup failed." }
} finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $uuidSql -Force -ErrorAction SilentlyContinue
}

# Alembic migration using the private DB credentials as process environment.
Import-ProcessEnv $LocalDbEnv
$env:PYTHONPATH = $Backend
Push-Location (Join-Path $Backend "app")
try {
    & $DishPy -m alembic -c alembic.ini upgrade head
    if ($LASTEXITCODE -ne 0) { throw "Alembic upgrade failed." }
    & $DishPy -m alembic -c alembic.ini current
    if ($LASTEXITCODE -ne 0) { throw "Alembic current failed." }
} finally {
    Pop-Location
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
}

if (-not $SkipTests) {
    Push-Location $Root
    try {
        & $AgentPy -m pytest -q
        if ($LASTEXITCODE -ne 0) { throw "AgentPi tests failed." }
    } finally { Pop-Location }

    Push-Location $Backend
    try {
        $env:PYTHONPATH = $Backend
        & $DishPy -m pytest -q tests_windows
        if ($LASTEXITCODE -ne 0) { throw "DishChat bridge tests failed." }
    } finally {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
        Pop-Location
    }
}

if (-not $NoStart) {
    & (Join-Path $PSScriptRoot "start.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Stack start failed." }
}

Write-Host "============================================================"
Write-Host "AGENTPI001 WINDOWS INSTALL PASS"
Write-Host "Repo:      $Root"
Write-Host "DishChat:  http://127.0.0.1:3000/"
Write-Host "Backend:   http://127.0.0.1:8000/api/docs"
Write-Host "AgentPi:   http://127.0.0.1:8765/"
Write-Host "Postgres:  127.0.0.1:55432"
Write-Host "============================================================"
