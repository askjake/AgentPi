param([string]$Root = "")
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
if ([string]::IsNullOrWhiteSpace($Root)) { $Root = Split-Path -Parent $PSScriptRoot }
$Root = (Resolve-Path $Root).Path
$Backend = Join-Path $Root "dish-chat\backend"
$DishPy = Join-Path $Backend ".venv-windows\Scripts\python.exe"
$LogsRouter = Join-Path $Backend "app\logs\router.py"
$LocalEnv = Join-Path $Root "runtime\local-db.env"
$Run = Join-Path $Root "runtime"
if (-not (Test-Path $LogsRouter)) { throw "app.logs is still missing: $LogsRouter" }
if (-not (Test-Path $LocalEnv)) { throw "local-db.env missing" }
if (-not (Test-Path $DishPy)) { throw "DishChat Windows venv missing: $DishPy" }

$probePath = Join-Path $Run "verify-local-source-db.py"
$probe = @'
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

root = Path(__file__).resolve().parents[1]
backend = root / "dish-chat" / "backend"
sys.path.insert(0, str(backend))
os.chdir(backend)
load_dotenv(root / "runtime" / "local-db.env", override=True)
os.environ["AUTH_DISABLED"] = "true"
os.environ["LOCAL"] = "true"
os.environ["IDLE_CHAT_CHECKER_ENABLED"] = "false"
os.environ["ENABLE_BETAREPORT_MCP"] = "false"
os.environ["ENABLE_VIEWERSHIP_MCP"] = "false"
os.environ["ENABLE_LOG_ASSIST_MCP"] = "false"
os.environ["ENABLE_INTERNAL_TOOLS_MCP"] = "false"

import psycopg
with psycopg.connect(
    host=os.environ["POSTGRES_HOST"],
    port=int(os.environ["POSTGRES_PORT"]),
    dbname=os.environ["POSTGRES_DB"],
    user=os.environ["POSTGRES_USER"],
    password=os.environ["POSTGRES_PWD"],
) as conn:
    with conn.cursor() as cur:
        cur.execute("select version_num from alembic_version")
        revs = {r[0] for r in cur.fetchall()}
        assert "20260918_fix_message_role_enum" in revs, revs
        cur.execute("select extname from pg_extension where extname='uuid-ossp'")
        assert cur.fetchone() == ("uuid-ossp",)

import app.main
print("DISHCHAT FULL APP IMPORT OK")
print("LOCAL POSTGRESQL SCHEMA OK")
'@
Set-Content -LiteralPath $probePath -Value $probe -Encoding UTF8
try {
    & $DishPy $probePath
    if ($LASTEXITCODE -ne 0) { throw "Full source/local DB verification failed" }
} finally {
    Remove-Item -LiteralPath $probePath -Force -ErrorAction SilentlyContinue
}
Write-Host "VERIFY LOCAL SOURCE + DB PASS"
