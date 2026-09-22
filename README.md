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
| DishChat frontend | `3000` |
| DishChat backend | `8000` |
| AgentPi sidecar | `8765` |
| Windows portable PostgreSQL | `55432` |
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

Open the UI at:

```text
http://127.0.0.1:3000/
```

For LAN access on Linux, use the host IP on port `3000`. The frontend calls the backend on port `8000` of the same hostname.

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
