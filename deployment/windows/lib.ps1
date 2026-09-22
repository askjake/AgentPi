Set-StrictMode -Version Latest

function Get-AgentPiRepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

function Ensure-Directory([string]$Path) {
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

function Resolve-Python313 {
    $candidates = New-Object System.Collections.Generic.List[string]

    try {
        $p = (& py -3.13 -c "import sys; print(sys.executable)" 2>$null | Select-Object -First 1)
        if ($LASTEXITCODE -eq 0 -and $p) { $candidates.Add($p.Trim()) }
    } catch {}

    $candidates.Add((Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"))
    $candidates.Add("python3.13.exe")
    $candidates.Add("python3.13")

    function Test-Python313([string]$Candidate) {
        if ([string]::IsNullOrWhiteSpace($Candidate)) { return $false }
        try {
            & $Candidate -c "import sys; assert sys.version_info[:2] == (3,13)" 2>$null
            return ($LASTEXITCODE -eq 0)
        } catch {
            return $false
        }
    }

    foreach ($candidate in $candidates) {
        if (Test-Python313 $candidate) { return $candidate }
    }

    Write-Host "Python 3.13 is not installed. Bootstrapping a per-user installation..."

    # A Windows App Installer execution alias can exist even when winget itself is
    # missing/broken. Only use winget after proving the executable can run.
    $wingetPath = $null
    try {
        $wingetCmd = Get-Command winget.exe -ErrorAction SilentlyContinue
        if ($wingetCmd -and $wingetCmd.Source) {
            & $wingetCmd.Source --version *> $null
            if ($LASTEXITCODE -eq 0) { $wingetPath = $wingetCmd.Source }
        }
    } catch {
        $wingetPath = $null
    }

    if ($wingetPath) {
        try {
            Write-Host "Trying Python 3.13 installation with winget..."
            & $wingetPath install --id Python.Python.3.13 -e --scope user --accept-package-agreements --accept-source-agreements
            if ($LASTEXITCODE -eq 0) {
                $direct = Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"
                if (Test-Python313 $direct) { return $direct }
            }
        } catch {
            Write-Warning "winget installation path failed; falling back to the official Python.org installer."
        }
    } else {
        Write-Host "winget is unavailable or its execution alias is broken; using Python.org directly."
    }

    # Official Python.org Windows x64 installer for the maintained 3.13 series.
    $pythonVersion = "3.13.15"
    $pythonUrl = "https://www.python.org/ftp/python/$pythonVersion/python-$pythonVersion-amd64.exe"
    $pythonSha256 = "edec09c4853aeae9ac36efb8c9f95b6b8e2fee65eee56d9767a8b7c69c574403"
    $installer = Join-Path $env:TEMP "python-$pythonVersion-amd64.exe"

    Write-Host "Downloading official Python $pythonVersion installer..."
    Invoke-WebRequest -UseBasicParsing -Uri $pythonUrl -OutFile $installer

    $actualSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $installer).Hash.ToLowerInvariant()
    if ($actualSha -ne $pythonSha256) {
        Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue
        throw "Python installer SHA-256 verification failed."
    }

    try {
        Write-Host "Installing Python $pythonVersion for the current user..."
        $proc = Start-Process -FilePath $installer -ArgumentList @(
            "/quiet",
            "InstallAllUsers=0",
            "PrependPath=0",
            "Include_pip=1",
            "Include_launcher=1",
            "Include_test=0",
            "AssociateFiles=0",
            "Shortcuts=0"
        ) -Wait -PassThru

        if ($proc.ExitCode -ne 0) {
            throw "Python.org installer exited with code $($proc.ExitCode)."
        }
    } finally {
        Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue
    }

    $direct = Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"
    if (Test-Python313 $direct) { return $direct }

    # Last-resort discovery in case the official installer selected a patch-specific
    # per-user path that differs from the usual Python313 directory.
    $pythonRoot = Join-Path $env:LOCALAPPDATA "Programs\Python"
    if (Test-Path $pythonRoot) {
        foreach ($candidate in Get-ChildItem -Path $pythonRoot -Filter python.exe -File -Recurse -ErrorAction SilentlyContinue) {
            if (Test-Python313 $candidate.FullName) { return $candidate.FullName }
        }
    }

    throw "Python 3.13 installation completed but a working 3.13 interpreter could not be found."
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
