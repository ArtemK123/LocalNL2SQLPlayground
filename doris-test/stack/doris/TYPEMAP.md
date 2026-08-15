# PostgreSQL → Doris type mapping (codegen defaults)

| PostgreSQL | Doris |
|------------|-------|
| smallint, integer | INT |
| bigint | BIGINT |
| real, double precision | DOUBLE |
| numeric, decimal | DECIMAL(38,9) |
| boolean | BOOLEAN |
| text, varchar, char | STRING |
| date | DATE |
| timestamp without time zone | DATETIME |
| timestamp with time zone | DATETIME |
| json, jsonb | STRING |
| uuid | STRING |
| bytea | STRING |

Debezium unwrap adds `` `__deleted` `` and `` `__source_ts_ms` `` on ODS tables.

Regenerate artifacts: `python scripts/codegen/generate_cdc.py --pg-dsn postgresql://bird:bird@127.0.0.1:55432/bird`
