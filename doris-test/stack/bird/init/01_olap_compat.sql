-- Optional superuser-style OLAP login used by PremSQL / Vanna stacks in this repo.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'olap') THEN
    CREATE ROLE olap LOGIN PASSWORD 'olap' SUPERUSER;
  END IF;
END
$$;
