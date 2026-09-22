param(
    [string]$CoverityAssistToken = "",
    [string]$DefaultUserEmail = "local@localhost",
    [string]$PostgresBuild = "17.11-4",
    [switch]$NonInteractive,
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

if ([string]::IsNullOrWhiteSpace($CoverityAssistToken)) {
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

if (-not (Test-Path (Join-Path $PgBin "initdb.exe"))) {
    if (-not (Test-Path $PgZip)) {
        $url = "https://get.enterprisedb.com/postgresql/postgresql-$PostgresBuild-windows-x64-binaries.zip"
        Write-Host "Downloading PostgreSQL $PostgresBuild..."
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $PgZip
    }
    if (Test-Path $PgHome) { Remove-Item -Recurse -Force $PgHome }
    Ensure-Directory $PgHome
    $tar = Get-Command tar.exe -ErrorAction SilentlyContinue
    if ($tar) {
        & tar.exe -xf $PgZip -C $PgHome
        if ($LASTEXITCODE -ne 0) { throw "tar.exe failed to extract PostgreSQL." }
    } else {
        Expand-Archive -LiteralPath $PgZip -DestinationPath $PgHome -Force
    }
}
foreach ($exe in @("initdb.exe","pg_ctl.exe","pg_isready.exe","psql.exe","createdb.exe","dropdb.exe","pg_dump.exe","pg_restore.exe")) {
    if (-not (Test-Path (Join-Path $PgBin $exe))) { throw "Portable PostgreSQL missing $exe" }
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
$admin = Read-DotEnv $AdminEnv
$db = Read-DotEnv $LocalDbEnv
$env:PGPASSWORD = $admin["POSTGRES_ADMIN_PWD"]
try {
    & (Join-Path $PgBin "psql.exe") -h 127.0.0.1 -p 55432 -U $admin["POSTGRES_ADMIN_USER"] -d $db["POSTGRES_DB"] -v ON_ERROR_STOP=1 -c 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp";'
    if ($LASTEXITCODE -ne 0) { throw "uuid-ossp setup failed." }
} finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
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
