AgentPi001 Windows Local DB R1-R2 hotfix

Purpose:
- preserve the existing initialized local PostgreSQL cluster
- enable uuid-ossp required by the Journal migration
- resume Alembic upgrade head
- avoid Windows PowerShell 5.1 multiline python -c quoting failures
- correct app.logs recovery verification (no __init__.py exists in the live Pi source)

Apply by extracting this directory under the full AgentPi001 bundle, then run:
  powershell -NoProfile -ExecutionPolicy Bypass -File .\AgentPi001-windows-local-db-r1-r2-hotfix-20260922\MIGRATE_LOCAL_DB.ps1 -Root "%CD%"
  powershell -NoProfile -ExecutionPolicy Bypass -File .\AgentPi001-windows-local-db-r1-r2-hotfix-20260922\VERIFY_LOCAL_SOURCE_AND_DB.ps1 -Root "%CD%"

No initdb, database reset, credential rotation, or Pi DB access is performed by these scripts.
