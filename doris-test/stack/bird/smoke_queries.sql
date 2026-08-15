-- Sample Formula 1 queries for DB smoke (from MINIDEV gold set; not harness).
SELECT T2.driverRef FROM qualifying AS T1 INNER JOIN drivers AS T2 ON T2.driverId = T1.driverId WHERE T1.raceId = 20 ORDER BY T1.q1 DESC NULLS LAST LIMIT 5;
SELECT DISTINCT T2.name FROM circuits AS T1 INNER JOIN races AS T2 ON T2.circuitID = T1.circuitId WHERE T1.country = 'Germany';
SELECT COUNT(*)::int AS table_count FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog', 'information_schema');
