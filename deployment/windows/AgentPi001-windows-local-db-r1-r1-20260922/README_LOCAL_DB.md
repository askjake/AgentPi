# AgentPi001 Windows local PostgreSQL repair

This overlay fixes two issues in the first full Windows handoff:

1. `dish-chat/backend/app/logs/` was accidentally excluded by the handoff's broad `logs/` rsync exclusion. `RECOVER_MISSING_APP_LOGS.ps1` restores only that source package from the Pi.
2. Replaces the temporary Pi PostgreSQL SSH tunnel with a private user-space PostgreSQL cluster stored under this Windows deployment's `runtime/` directory.

The local database is **fresh and independent**. It does not copy Pi data. Alembic upgrades it to the DishChat source head `20260918_fix_message_role_enum`. If a copy of Pi chats/journal data is desired later, do that as a separate reviewed pg_dump/pg_restore operation.

PostgreSQL binaries are downloaded from EDB's official Windows binary archive host. They are not installed as a Windows service and require no administrator privileges. PostgreSQL listens only on `127.0.0.1:55432`.

Run from the existing full bundle root (CMD examples):

```bat
powershell -NoProfile -ExecutionPolicy Bypass -File ".\local-db-r1-r1\RECOVER_MISSING_APP_LOGS.ps1" -Root "%CD%" -PiHost "10.73.184.96" -PiUser "agentpi001"

powershell -NoProfile -ExecutionPolicy Bypass -File ".\local-db-r1-r1\SETUP_LOCAL_POSTGRES.ps1" -Root "%CD%"

powershell -NoProfile -ExecutionPolicy Bypass -File ".\local-db-r1-r1\VERIFY_LOCAL_SOURCE_AND_DB.ps1" -Root "%CD%"

powershell -NoProfile -ExecutionPolicy Bypass -File ".\local-db-r1-r1\START_FULL_STACK_LOCAL_DB.ps1" -Root "%CD%"
```

Local database credentials are generated randomly and stored only in:

- `runtime/local-db.env` (application role)
- `runtime/local-db-admin.env` (local PostgreSQL admin)

Do not upload those two files.
