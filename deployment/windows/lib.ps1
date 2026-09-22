Set-StrictMode -Version Latest

function Get-AgentPiRepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

function Ensure-Directory([string]$Path) {
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

function Resolve-Python313 {
    $candidates = @()
    try {
        $p = (& py -3.13 -c "import sys; print(sys.executable)" 2>$null | Select-Object -First 1)
        if ($LASTEXITCODE -eq 0 -and $p) { $candidates += $p.Trim() }
    } catch {}
    $candidates += @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"),
        "python3.13.exe",
        "python3.13"
    )
    foreach ($candidate in $candidates) {
        if (-not $candidate) { continue }
        try {
            & $candidate -c "import sys; assert sys.version_info[:2] == (3,13)" 2>$null
            if ($LASTEXITCODE -eq 0) { return $candidate }
        } catch {}
    }

    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "Python 3.13 is required. Install it and rerun."
    }
    Write-Host "Installing Python 3.13 for the current user..."
    & winget.exe install --id Python.Python.3.13 -e --scope user --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "Python 3.13 installation failed." }

    $direct = Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"
    if (-not (Test-Path $direct)) {
        throw "Python 3.13 installed but executable was not found. Open a new terminal and rerun."
    }
    return $direct
}

function Read-DotEnv([string]$Path) {
    $result = @{}
    if (-not (Test-Path $Path)) { return $result }
    foreach ($raw in Get-Content -LiteralPath $Path) {
        $line = $raw.Trim()
        if (-not $line -or $line.StartsWith("#")) { continue }
        $parts = $line.Split("=", 2)
        if ($parts.Count -eq 2) { $result[$parts[0]] = $parts[1] }
    }
    return $result
}

function Set-DotEnvValue([string]$Path, [string]$Key, [string]$Value, [switch]$OnlyIfMissing) {
    $lines = @()
    if (Test-Path $Path) { $lines = @(Get-Content -LiteralPath $Path) }
    $found = $false
    $out = New-Object System.Collections.Generic.List[string]
    foreach ($line in $lines) {
        if ($line -match "^\s*$([Regex]::Escape($Key))=") {
            $found = $true
            if ($OnlyIfMissing) { $out.Add($line) } else { $out.Add("$Key=$Value") }
        } else {
            $out.Add($line)
        }
    }
    if (-not $found) { $out.Add("$Key=$Value") }
    [IO.File]::WriteAllLines($Path, $out, [Text.UTF8Encoding]::new($false))
}

function New-HexSecret([int]$Bytes = 24) {
    $buffer = New-Object byte[] $Bytes
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($buffer) } finally { $rng.Dispose() }
    return ([BitConverter]::ToString($buffer)).Replace("-", "").ToLowerInvariant()
}

function New-MasterKey {
    $buffer = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($buffer) } finally { $rng.Dispose() }
    return [Convert]::ToBase64String($buffer)
}

function Get-PgPaths([string]$Root) {
    $run = Join-Path $Root "runtime"
    $versionFile = Join-Path $run "postgresql-version.txt"
    if (-not (Test-Path $versionFile)) { throw "PostgreSQL version marker missing: $versionFile" }
    $version = (Get-Content -LiteralPath $versionFile | Select-Object -First 1).Trim()
    $pgBin = Join-Path $run "postgresql-$version\pgsql\bin"
    return @{
        Run = $run
        Version = $version
        Bin = $pgBin
        Data = (Join-Path $run "postgres-data")
        Env = (Join-Path $run "local-db.env")
        AdminEnv = (Join-Path $run "local-db-admin.env")
        Log = (Join-Path $run "logs\postgresql.log")
    }
}

function Start-AgentPiPostgres([string]$Root) {
    $pg = Get-PgPaths $Root
    Ensure-Directory (Split-Path -Parent $pg.Log)
    $ctl = Join-Path $pg.Bin "pg_ctl.exe"
    $ready = Join-Path $pg.Bin "pg_isready.exe"
    if (-not (Test-Path $ctl)) { throw "Missing $ctl" }
    if (-not (Test-Path (Join-Path $pg.Data "PG_VERSION"))) { throw "PostgreSQL cluster is not initialized." }

    & $ctl status -D $pg.Data *> $null
    if ($LASTEXITCODE -ne 0) {
        & $ctl -D $pg.Data -l $pg.Log -w start
        if ($LASTEXITCODE -ne 0) { throw "PostgreSQL failed to start. See $($pg.Log)" }
    }
    & $ready -h 127.0.0.1 -p 55432
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL is not ready on 127.0.0.1:55432" }
}

function Stop-AgentPiPostgres([string]$Root) {
    try { $pg = Get-PgPaths $Root } catch { return }
    $ctl = Join-Path $pg.Bin "pg_ctl.exe"
    if ((Test-Path $ctl) -and (Test-Path (Join-Path $pg.Data "PG_VERSION"))) {
        & $ctl status -D $pg.Data *> $null
        if ($LASTEXITCODE -eq 0) {
            & $ctl -D $pg.Data -w stop -m fast
        }
    }
}

function Import-ProcessEnv([string]$Path) {
    $values = Read-DotEnv $Path
    foreach ($key in $values.Keys) {
        [Environment]::SetEnvironmentVariable($key, $values[$key], "Process")
    }
}

function Wait-Http([string]$Name, [string]$Url, [int]$Attempts = 30) {
    for ($i = 0; $i -lt $Attempts; $i++) {
        try {
            $r = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
            if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 400) {
                Write-Host ("PASS {0,-18} {1} -> {2}" -f $Name, $Url, $r.StatusCode)
                return $true
            }
        } catch {}
        Start-Sleep -Seconds 1
    }
    Write-Warning "FAIL $Name $Url"
    return $false
}
