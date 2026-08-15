-- Read-only role for NL2SQL services (matches local stacks convention).
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nl2sql_ro') THEN
    CREATE ROLE nl2sql_ro LOGIN PASSWORD 'nl2sql_ro';
  END IF;
END
$$;

DO $$
BEGIN
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO nl2sql_ro', current_database());
END
$$;
