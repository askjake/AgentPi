param(
    [string]$RepoRoot = "",
    [string]$TargetBranch = "feature/bugfix-10-gaps",
    [string]$RequiredAncestor = "538db536edf6629b7061e9368334733292fe866a",
    [switch]$StartAndVerify
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
} else {
    $Root = (Resolve-Path $RepoRoot).Path
}
Push-Location $Root
try {
    Write-Host "=== AgentPi branch recovery/switch ==="
    Write-Host "Repo:   $Root"
    Write-Host "Target: $TargetBranch"

    $stop = Join-Path $Root "deployment\windows\stop.ps1"
    if (Test-Path $stop) {
        & $stop
    }

    Write-Host "Preserving existing stash entries:"
    & git stash list

    # Prevent Windows line-ending conversion from re-dirtying the tracked tree.
    & git config --local core.autocrlf false
    if ($LASTEXITCODE -ne 0) { throw "git config core.autocrlf failed" }

    # Make the single-branch clone permanently aware of the bugfix branch.
    & git remote set-branches --add origin $TargetBranch
    if ($LASTEXITCODE -ne 0) { throw "git remote set-branches failed" }

    & git fetch origin
    if ($LASTEXITCODE -ne 0) { throw "git fetch failed" }

    $remoteRef = "origin/$TargetBranch"
    $remoteSha = (& git rev-parse $remoteRef).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $remoteSha) { throw "Cannot resolve $remoteRef" }
    Write-Host "Remote SHA: $remoteSha"

    if ($RequiredAncestor) {
        & git merge-base --is-ancestor $RequiredAncestor $remoteRef
        if ($LASTEXITCODE -ne 0) {
            throw "Target $remoteRef is not a descendant of required baseline $RequiredAncestor."
        }
    }

    # This intentionally discards tracked working-tree line-ending noise only.
    # --no-overwrite-ignore protects ignored runtime/.env/database files.
    & git checkout -f --no-overwrite-ignore -B $TargetBranch $remoteRef
    if ($LASTEXITCODE -ne 0) { throw "git checkout failed" }

    & git branch --set-upstream-to=$remoteRef $TargetBranch
    if ($LASTEXITCODE -ne 0) { throw "setting upstream failed" }

    $branch = (& git branch --show-current).Trim()
    $head = (& git rev-parse HEAD).Trim()
    Write-Host "Current branch: $branch"
    Write-Host "Current SHA:    $head"

    if ($branch -ne $TargetBranch) { throw "Wrong branch after checkout: $branch" }
    if ($head -ne $remoteSha) { throw "Wrong HEAD after checkout: expected $remoteSha but found $head" }

    Write-Host "Tracked status:"
    & git status --short --branch

    $py = Join-Path $Root ".venv-windows\Scripts\python.exe"
    $test = Join-Path $Root "tests\patch_verify\test_integration.py"
    if (-not (Test-Path $py)) { throw "Missing AgentPi Windows venv: $py" }
    if (-not (Test-Path $test)) { throw "Missing bugfix integration test: $test" }

    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"

    & $py $test
    if ($LASTEXITCODE -ne 0) { throw "Bugfix integration tests failed" }

    if ($StartAndVerify) {
        $start = Join-Path $Root "deployment\windows\start.ps1"
        $verify = Join-Path $Root "deployment\windows\verify.ps1"

        & $start -OpenBrowser
        if ($LASTEXITCODE -ne 0) { throw "Stack start failed" }

        & $verify
        if ($LASTEXITCODE -ne 0) { throw "Stack verification failed" }

        $agentPiPort = 8765
        $agentPiPortFile = Join-Path $Root "runtime\agentpi-port.txt"
        if (Test-Path $agentPiPortFile) {
            $saved = (Get-Content -LiteralPath $agentPiPortFile -ErrorAction SilentlyContinue | Select-Object -First 1)
            $parsed = 0
            if ([int]::TryParse("$saved", [ref]$parsed) -and $parsed -gt 0 -and $parsed -lt 65536) {
                $agentPiPort = $parsed
            }
        }

        foreach ($url in @(
            ("http://127.0.0.1:{0}/rest/api/v1/health" -f $agentPiPort),
            "http://127.0.0.1:8000/rest/api/v1/health",
            "http://127.0.0.1:3000/health"
        )) {
            $r = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 5
            Write-Host ("HEALTH {0} -> {1}" -f $url, $r.StatusCode)
            if ($r.StatusCode -ne 200) { throw "Health check failed: $url" }
        }

        Write-Host "Listening endpoints:"
        Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
            Where-Object { $_.LocalPort -in @($agentPiPort,8000,3000) } |
            Sort-Object LocalPort |
            Format-Table LocalAddress,LocalPort,State,OwningProcess -AutoSize

        $db = Join-Path $Root "runtime\agentpi-devices.db"
        if (-not (Test-Path $db)) { throw "Expected AgentPi SQLite DB was not created: $db" }
        Write-Host "AgentPi SQLite DB: $db"
    }

    Write-Host "=== PASS ==="
} finally {
    Pop-Location
}
