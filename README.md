# AgentPi001

AgentPi001 combines:

- the AgentPi device-discovery/runtime sidecar,
- the full DishChat FastAPI agent backend,
- the DishChat browser frontend,
- PostgreSQL persistence and Alembic migrations,
- AgentPi tools exposed to the DishChat agent,
- Coverity Assist LLM integration.

The portable deployment tooling lives under `deployment/windows` and `deployment/linux`.

## Supported branch

```text
feature/agentpi-initial
```

The first full-stack working snapshot was commit:

```text
37d16f0e58e7181cc2ede3c789359d005b177cdc
```

Later commits on the same branch add deployment hardening and self-install scripts.

## Service ports

| Service | Default |
| --- | --- |
| DishChat frontend | `0.0.0.0:3000` |
| DishChat backend | `0.0.0.0:8000` |
| AgentPi sidecar | loopback `8765` preferred; automatic fallback on Windows |
| Windows portable PostgreSQL | `127.0.0.1:55432` |
| Linux PostgreSQL | `5432` |

## Supported deployment entry points

| Platform | Fresh install | Update | Start / stop / verify |
| --- | --- | --- | --- |
| Windows | `deployment/windows/install.ps1` | `deployment/windows/update.ps1` | `start.ps1`, `stop.ps1`, `verify.ps1` |
| Linux / Raspberry Pi OS | `deployment/linux/install.sh` | `deployment/linux/update.sh` | `start.sh`, `stop.sh`, `verify.sh` |

Both platforms also include database backup/restore scripts and an `adopt-legacy` helper for migrating an older running installation into the repo-native layout.

## Windows: fresh install

Requirements: Windows 10/11 and network access. If Python 3.13 is missing, the installer first tries a working `winget`; if `winget` is unavailable or its App Installer execution alias is broken, it downloads the official Python.org 3.13 x64 installer, verifies its SHA-256, and installs Python per-user without administrator rights.

```bat
git clone --branch feature/agentpi-initial --single-branch https://github.com/askjake/AgentPi.git
cd AgentPi
powershell -NoProfile -ExecutionPolicy Bypass -File ".\deployment\windows\install.ps1"
```

The installer:

- creates isolated AgentPi and DishChat Python 3.13 environments,
- installs the exact qualified dependency freezes,
- downloads PostgreSQL 17.11 portable binaries,
- creates a private PostgreSQL cluster under `runtime\postgres-data`,
- generates DB credentials and an application master key,
- enables `uuid-ossp`,
- runs Alembic to `head`,
- runs the AgentPi and bridge tests,
- starts and verifies all services.

The Coverity Assist token is prompted without echo. For automation:

```bat
set COVERITY_ASSIST_TOKEN=your-token
powershell -NoProfile -ExecutionPolicy Bypass -File ".\deployment\windows\install.ps1" -NonInteractive
set COVERITY_ASSIST_TOKEN=
```

If the wrong Coverity Assist token was entered previously, replace only that secret and resume the installer:

```bat
powershell -NoProfile -ExecutionPolicy Bypass -File ".\deployment\windows\install.ps1" -ResetCoverityAssistToken
```

The replacement token is prompted with secure input and overwrites the existing `COVERITY_ASSIST_TOKEN` entry in `dish-chat\backend\.env`. Existing PostgreSQL data is preserved.

### Windows operations

```bat
powershell -NoProfile -ExecutionPolicy Bypass -File ".\deployment\windows\start.ps1" -OpenBrowser
powershell -NoProfile -ExecutionPolicy Bypass -File ".\deployment\windows\verify.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File ".\deployment\windows\stop.ps1"
```

Update the current installation from the branch. The updater backs up PostgreSQL before changing code or running migrations:

```bat
powershell -NoProfile -ExecutionPolicy Bypass -File ".\deployment\windows\update.ps1"
```

Manual DB backup:

```bat
powershell -NoProfile -ExecutionPolicy Bypass -File ".\deployment\windows\backup-db.ps1"
```

Restore is destructive and therefore requires `-Force`:

```bat
powershell -NoProfile -ExecutionPolicy Bypass -File ".\deployment\windows\restore-db.ps1" -BackupPath ".\runtime\backups\dishchat-YYYYMMDDTHHMMSSZ.dump" -Force
```

Windows runtime secrets and the portable PostgreSQL data directory live under ignored `.env` / `runtime` paths and are not committed.

Windows may reserve port `8765` through its excluded TCP port mechanism. The launcher probes `8765` first and automatically falls back to `18765`, `28765`, `38765`, or `48765` if needed. The selected port is saved in `runtime\agentpi-port.txt`; DishChat and `verify.ps1` read the same endpoint automatically.

## Linux: fresh install

The supported automatic package-install path is Debian/Ubuntu/Raspberry Pi OS (`apt`). If Python 3.13 is unavailable from the distro packages, the installer bootstraps `uv` for the current user and installs Python 3.13 through it. Systems with Git, curl, OpenSSL, and PostgreSQL already installed can also use the same script.

```bash
git clone --branch feature/agentpi-initial --single-branch https://github.com/askjake/AgentPi.git
cd AgentPi
bash deployment/linux/install.sh
```

The Linux installer prompts securely for the Coverity Assist token and creates:

```text
.venv
dish-chat/backend/.venv
dish-chat/backend/.env
runtime/
```

For non-interactive installation:

```bash
export COVERITY_ASSIST_TOKEN='your-token'
bash deployment/linux/install.sh --non-interactive
unset COVERITY_ASSIST_TOKEN
```

### Linux operations

```bash
bash deployment/linux/start.sh
bash deployment/linux/verify.sh
bash deployment/linux/stop.sh
```

Update from the current branch:

```bash
bash deployment/linux/update.sh
```

The updater:

1. refuses tracked local modifications,
2. creates a PostgreSQL backup,
3. records the pre-update Git SHA,
4. stops the application processes,
5. fetches and fast-forwards the branch,
6. refreshes dependencies,
7. applies Alembic migrations,
8. restarts and verifies the stack.

Manual DB backup:

```bash
bash deployment/linux/backup-db.sh
```

Destructive restore:

```bash
bash deployment/linux/restore-db.sh runtime/backups/dishchat-YYYYMMDDTHHMMSSZ.dump --force
```

## Verify manually

Windows:

```bat
curl.exe -fsS http://127.0.0.1:8765/rest/api/v1/health
curl.exe -fsS http://127.0.0.1:8000/rest/api/v1/health
curl.exe -fsS http://127.0.0.1:3000/health
```

Linux:

```bash
curl -fsS http://127.0.0.1:8765/rest/api/v1/health
curl -fsS http://127.0.0.1:8000/rest/api/v1/health
curl -fsS http://127.0.0.1:3000/health
```

Open the UI locally at:

```text
http://127.0.0.1:3000/
```

The supported deployment binds the DishChat frontend to `0.0.0.0:3000` and backend to `0.0.0.0:8000`, so another device on the LAN can use:

```text
http://<HOST_LAN_IP>:3000/
```

The browser automatically calls `http://<HOST_LAN_IP>:8000`. AgentPi (`8765`) and PostgreSQL remain loopback-only by design. On Windows, inbound access can still be blocked by Windows Defender Firewall; allow Python/private-network access or add inbound rules for TCP 3000 and 8000 if required.

## Database

The current migration head included in this branch is:

```text
20260918_fix_message_role_enum
```

The Journal schema requires PostgreSQL extension:

```text
uuid-ossp
```

The install scripts enable that extension before Alembic migrations.

Windows uses a private portable cluster under `runtime\postgres-data` and does not require a machine-wide PostgreSQL installation.

Linux uses the system PostgreSQL service and creates:

```text
role:     agentpi_local
database: dishchat_local
```

The generated password is stored only in the ignored `dish-chat/backend/.env`.

## LLM configuration

The qualified configuration uses:

```text
PLLM_PROVIDER=coverity-assist
ELLM_PROVIDER=coverity-assist
DEFAULT_MODEL_PREFERENCE=reasoning
```

Do not print or log the full Pydantic `Settings` object because it can contain credentials.

Optional MCP and external-service credentials belong in `dish-chat/backend/.env`. See:

```text
dish-chat/backend/.env.example
```

## Windows LangGraph checkpoint behavior

On Windows, the backend uses LangGraph `MemorySaver` because Psycopg asynchronous connections timed out even with a Windows selector event loop. Application data such as chats, messages, users, Journal, vault, analytics, and other DishChat tables still persists in PostgreSQL.

Linux continues to use the PostgreSQL LangGraph checkpointer.

## Rollback after update

Each updater records the old source SHA at:

```text
runtime/pre-update-git-sha.txt
```

and creates a DB backup under:

```text
runtime/backups/
```

To roll source back:

```bash
git reset --hard <old-sha>
```

or on Windows:

```bat
git reset --hard <old-sha>
```

If the update included an incompatible database migration, restore the pre-update DB dump using the platform restore script before restarting the old code.

## Adopt an existing legacy installation

If a Windows machine is currently running the earlier bundle layout, first clone this branch into a **new** directory, then migrate the existing runtime/database state:

```bat
cd AgentPi
powershell -NoProfile -ExecutionPolicy Bypass -File ".\deployment\windows\adopt-legacy.ps1" -LegacyRoot "C:\path\to\old\AgentPi001-full-windows-r1-20260922"
```

The old tree is stopped and preserved; its portable PostgreSQL cluster and environment files are copied into the repo-native clone, migrations are applied, and the new stack is started and verified.

For an older Linux/Raspberry Pi layout with a sibling `~/dish-chat` tree, clone the branch into `~/AgentPi` (or another new repo-native path), then:

```bash
cd ~/AgentPi
bash deployment/linux/adopt-legacy.sh ~/dish-chat
```

The script preserves a tar backup of the legacy source, stops the known DishChat systemd units when present, reuses the existing database configuration, applies migrations, and starts/verifies the repo-native stack.

## Legacy Raspberry Pi deployment

Older Raspberry Pi installs may have this layout:

```text
/home/agentpi001/AgentPi
/home/agentpi001/dish-chat
```

The new supported installers are **repo-root-native** and use:

```text
<clone>/dish-chat
```

Do not point the new updater at the sibling legacy live tree. Either migrate that host to the repo-native layout, or back up its database and `.env`, deploy a fresh repo-native copy, and restore/reuse the existing database configuration.

## Security

The repository intentionally excludes:

- `.env` files,
- PostgreSQL data directories,
- local runtime logs/PIDs,
- generated credentials,
- virtual environments.

Generic development defaults may exist in source, but service tokens and machine-specific secrets must remain in environment files.


## Backend longevity

Streaming chat responses no longer hold request-scoped PostgreSQL sessions for the full SSE/LLM lifetime. Initial authorization/checkpoint setup uses a short DB context, the stream runs without pinning an application DB connection, and usage metadata is written afterward with its own short-lived session.

The SQLAlchemy pool is configured with pre-ping, bounded checkout wait, connection recycling, and LIFO reuse. A PostgreSQL readiness endpoint is available at:

```text
/rest/api/v1/health/db
```

It executes a real `SELECT 1` and returns non-secret pool diagnostics. The Windows verifier checks this endpoint.

## Environment-aware network mapping

Dish-Agent now detects native Windows, WSL, and Linux separately. Native Windows guidance explicitly prevents Linux-only command assumptions such as `ip addr`, `hostname -I`, and Linux ping flags.

Requests such as:

```text
scan my network and map all devices that you find
```

are routed directly to the local AgentPi bridge. AgentPi performs bounded active neighbor discovery plus mDNS, persists discovered devices in its SQLite inventory, and returns the combined map. Shell-based `nmap`/`ip`/`ipconfig` discovery is only a fallback when the AgentPi bridge is unavailable.

Active discovery does not require administrator rights. It warms the OS neighbor table by touching addresses on attached private IPv4 subnets and then reads the native ARP/neighbor table. Windows and Linux ping argument syntax are handled separately.


Windows local deployments default the idle Journal checker off to avoid periodic background LLM/database work competing with interactive chat sessions. Set `IDLE_CHAT_CHECKER_ENABLED=true` explicitly in `dish-chat/backend/.env` if you intentionally want that background feature enabled on Windows.


## Native Windows execution semantics

Dish-Agent does not need to discover Python through `PATH` on a Windows deployment. The backend is already running under a known-good interpreter, and `agent_run_python` / `agent_create_venv` reuse `sys.executable` when no workspace venv or explicit interpreter is supplied.

Specific TCP port checks use Python's socket API through `agent_check_device`; they do not depend on `nc`, `netcat`, PowerShell, or other external networking binaries. Missing optional SSH clients are reported as an unavailable capability rather than surfacing `WinError 2`.

Arbitrary PowerShell remains outside the generic `agent_run_shell` allowlist by design. Network discovery, TCP probing, and Python execution have dedicated cross-platform tools and should not fall back to PowerShell or PATH probing.


## Local public web search

Portable/local AgentPi installs do not start the historical Coverity gateway on `127.0.0.1:5000`. Public web search therefore defaults to a direct local-client path on Windows: DuckDuckGo's non-JavaScript HTML endpoint first, then Lite as a fallback. The query sanitizer still blocks credentials, employee/company addresses, and private IPs before any public request is made.

Search mode is controlled by `PUBLIC_WEB_SEARCH_MODE=auto|direct|gateway`. In `auto`, `LOCAL=true` selects direct search; non-local deployments preserve gateway mode. Windows installation writes `PUBLIC_WEB_SEARCH_MODE=direct` explicitly.

Use `public_web_search_status` or `GET /rest/api/v1/health/search?probe=true` to distinguish search-backend availability from general host connectivity. The Windows execution-boundary qualification performs the live probe after restart.


### Deterministic search rendering

Fresh public-search results remain structured JSON inside the tool boundary, but the chat planner renders that verified payload into Markdown without a second LLM pass. The renderer preserves result titles, validated HTTP(S) links, snippets, backend/source/TLS/cache evidence, and bounded provider-attempt receipts. Result text is Markdown-escaped and link destinations are validated/encoded before display.

Malformed/non-JSON search output fails closed with no inferred links. Structured search failures render their actual backend and attempt evidence instead of being replaced by generic planner prose.


### Genealogy identity continuity

For person-specific genealogy requests, a deterministic preflight runs before the model planner. The preflight extracts the explicit person target from the current/prior user turns, carries forward already-stated birth/death years, and invokes the identity tool with structured input. Conflicts and lineage-without-ancestor-evidence therefore return before any model/provider synthesis.

Person-specific genealogy work uses a read-only `agent_genealogy_identity_check` gate before a same/similar-name GEDCOM record may be treated as the research target. The tool can inspect a workspace `.ged` directly or read a single GEDCOM from a workspace ZIP without extracting it. Candidate evidence includes GEDCOM ID, name, birth/death dates and places, FAMC/FAMS-derived parents/spouses/children, and a bounded ancestor walk.

The identity contract returns `match`, `ambiguous`, `conflict`, or `not_found`. Only `match` permits identity continuity. Known years already present in the conversation are injected into the identity check when the planner omits them; a conflicting or missing expected date prevents a match.

Branch/lineage membership is a separate evidence gate. A surname or spouse relationship is not proof that a person belongs to the main family branch. Branch conclusions require FAMC/parent/ancestor evidence; if the matched record has no such evidence, the planner returns `GENEALOGY_LINEAGE_EVIDENCE_REQUIRED` instead of guessing.


### Text-transformation routing boundary

Rewrite, edit, polish, translate, summarize, shorten, expand, and similar requests treat the supplied prompt/template as inert content. Embedded instructions such as `public_web_search`, genealogy research steps, or execution directives do not trigger tools merely because they appear inside text being transformed.

The execution boundary rejects planner tool actions during a text-transformation request. After one rejection the planner is instructed to return a final transformed artifact only; repeated tool attempts fail closed with `TEXT_TRANSFORMATION_PROTOCOL_INVALID`. This prevents prior conversation context (for example, an ancestry/GEDCOM investigation) from leaking into an unrelated rewrite request.
