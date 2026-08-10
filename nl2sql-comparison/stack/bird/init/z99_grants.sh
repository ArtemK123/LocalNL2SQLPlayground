#!/bin/sh
set -eu
# Re-apply grants after optional seed SQL created objects in public (or other schemas).

psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" <<'SQL'
GRANT USAGE ON SCHEMA public TO nl2sql_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO nl2sql_ro;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO nl2sql_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO nl2sql_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON SEQUENCES TO nl2sql_ro;
SQL

# Optional: grant on all non-system schemas (BIRD multi-schema dumps)
for schema in $(psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -Atc \
  "SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg_%' AND nspname <> 'information_schema'"); do
  psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "GRANT USAGE ON SCHEMA \"${schema}\" TO nl2sql_ro;"
  psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "GRANT SELECT ON ALL TABLES IN SCHEMA \"${schema}\" TO nl2sql_ro;"
  psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "ALTER DEFAULT PRIVILEGES IN SCHEMA \"${schema}\" GRANT SELECT ON TABLES TO nl2sql_ro;"
done
