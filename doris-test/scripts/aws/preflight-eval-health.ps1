<#
.SYNOPSIS
  Pre-benchmark connectivity gate for dual-DSN scoring (Doris + optional PG gold).
#>
param(
    [string] $PredDsn = "mysql://root@127.0.0.1:9031/bird_minidev_olap",
    [string] $GoldDsn = "postgresql://olap:olap@127.0.0.1:55433/bird",
    [string] $Schemas = "california_schools,financial,formula_1",
    [int] $MinRows = 1,
    [switch] $SkipGold
)

$ErrorActionPreference = "Stop"
$env:PRED_DSN = $PredDsn
if (-not $SkipGold) { $env:GOLD_DSN = $GoldDsn } else { Remove-Item Env:GOLD_DSN -ErrorAction SilentlyContinue; $env:GOLD_DSN = "" }
$env:SCHEMAS = $Schemas
$env:MIN_ROWS = "$MinRows"

$sh = Join-Path $PSScriptRoot "preflight-eval-health.sh"
$gitBash = "C:\Program Files\Git\bin\bash.exe"
if (Test-Path $gitBash) {
    & $gitBash $sh
    if ($LASTEXITCODE -ne 0) { throw "preflight-eval-health failed ($LASTEXITCODE)" }
    exit 0
}

$bash = Get-Command bash -ErrorAction SilentlyContinue
$bashOk = $false
if ($bash) {
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & bash -c "exit 0" 2>$null | Out-Null
        $bashOk = ($LASTEXITCODE -eq 0)
    } catch {
        $bashOk = $false
    } finally {
        $ErrorActionPreference = $prevEap
    }
}
if ($bashOk) {
    & bash (Join-Path $PSScriptRoot "preflight-eval-health.sh")
    if ($LASTEXITCODE -ne 0) { throw "preflight-eval-health failed ($LASTEXITCODE)" }
    exit 0
}

$code = @'
import os
from urllib.parse import urlparse

pred = os.environ["PRED_DSN"]
gold = os.environ.get("GOLD_DSN", "").strip()
schemas = [s.strip() for s in os.environ.get("SCHEMAS", "").split(",") if s.strip()]
min_rows = int(os.environ.get("MIN_ROWS", "1"))

import pymysql

p = urlparse(pred)
conn = pymysql.connect(
    host=p.hostname or "127.0.0.1",
    port=p.port or 3306,
    user=p.username or "root",
    password=p.password or "",
    database=(p.path or "/").lstrip("/") or None,
    connect_timeout=10,
)
try:
    with conn.cursor() as cur:
        cur.execute("SELECT 1")
        cur.fetchone()
        print(f"DORIS_OK host={p.hostname}:{p.port}")
        for sch in schemas:
            cur.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema=%s AND table_type IN ('BASE TABLE','VIEW')",
                (sch,),
            )
            n_tables = int(cur.fetchone()[0])
            if n_tables < 1:
                raise SystemExit(f"SCHEMA_EMPTY schema={sch}")
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema=%s AND table_type IN ('BASE TABLE','VIEW') "
                "ORDER BY table_name LIMIT 1",
                (sch,),
            )
            tbl = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM `{}`.`{}`".format(sch, tbl))
            cnt = int(cur.fetchone()[0])
            print(f"SCHEMA_OK schema={sch} tables={n_tables} sample={sch}.{tbl} rows={cnt}")
            if cnt < min_rows:
                raise SystemExit(f"SCHEMA_TOO_FEW_ROWS {sch}.{tbl}={cnt}")
finally:
    conn.close()

if gold:
    import psycopg

    with psycopg.connect(gold, connect_timeout=10) as c:
        with c.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    print("GOLD_PG_OK")
print("PREFLIGHT_EVAL_HEALTH_OK")
'@

$py = Get-Command py -ErrorAction SilentlyContinue
if (-not $py) { throw "Python launcher 'py' not found" }
& py -3.13 -c $code
if ($LASTEXITCODE -ne 0) {
    & py -3 -c $code
}
if ($LASTEXITCODE -ne 0) { throw "preflight-eval-health failed ($LASTEXITCODE)" }
