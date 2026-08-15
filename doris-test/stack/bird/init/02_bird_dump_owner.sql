-- BIRD_dev.sql (pg_dump) issues ALTER ... OWNER TO xiaolongli; create the role first.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'xiaolongli') THEN
    CREATE ROLE xiaolongli;
  END IF;
END
$$;
