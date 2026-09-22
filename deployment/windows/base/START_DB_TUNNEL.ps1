param(
    [Parameter(Mandatory=$true)][string]$PiHost,
    [string]$PiUser = "agentpi001",
    [int]$LocalPort = 55432,
    [string]$Root = (Split-Path -Parent $PSScriptRoot)
)
$ErrorActionPreference = "Stop"
$ssh = Get-Command ssh.exe -ErrorAction SilentlyContinue
if (-not $ssh) { throw "Windows OpenSSH ssh.exe is unavailable." }
$Run = Join-Path $Root "runtime"
New-Item -ItemType Directory -Force -Path $Run | Out-Null
$PidFile = Join-Path $Run "db-tunnel.pid"

# If already listening, leave it alone.
$client = New-Object System.Net.Sockets.TcpClient
try {
    $iar = $client.BeginConnect("127.0.0.1", $LocalPort, $null, $null)
    if ($iar.AsyncWaitHandle.WaitOne(250) -and $client.Connected) {
        Write-Host "DB tunnel port 127.0.0.1:$LocalPort is already open."
        exit 0
    }
} catch {} finally { $client.Close() }

$args = @(
    "-N",
    "-L", "127.0.0.1:$LocalPort`:127.0.0.1:5432",
    "-o", "ExitOnForwardFailure=yes",
    "-o", "ServerAliveInterval=30",
    "-o", "ServerAliveCountMax=3",
    "$PiUser@$PiHost"
)
Write-Host "Starting SSH PostgreSQL tunnel. If SSH needs a password, a console may prompt for it."
$p = Start-Process -FilePath $ssh.Source -ArgumentList $args -PassThru
Set-Content -LiteralPath $PidFile -Value $p.Id
Start-Sleep -Seconds 2
if ($p.HasExited) { throw "SSH tunnel exited immediately with code $($p.ExitCode)" }
Write-Host "DB TUNNEL PID: $($p.Id)"
Write-Host "Local PostgreSQL endpoint: 127.0.0.1:$LocalPort"
