# Arctic vLLM — Doris vs SQLite vs Postgres (minidev-500)

**Package:** `doris-test/` (Doris dual-DSN) compared with `nl2sql-comparison/` (same-engine SQLite and Postgres).  
**Model:** `Snowflake/Arctic-Text2SQL-R1-7B` via vLLM, LangChain API, one-pass, 10 s, study-parity schema.  
**Primary Doris run:** `doris_20260815_113514` (full BIRD minidev, N=500).  
**Artifacts:** `doris-test/results/doris_20260815_113514/` (`jsonl/langchain_full.jsonl`, `summary.md`, `manifest.json`).  
**Deploy / runtime metrics** (hardware, VRAM, start-from-stopped, vLLM warm restart, harness latency): [`arctic-vllm-doris-deploy-runtime-metrics.md`](arctic-vllm-doris-deploy-runtime-metrics.md).  
**Counts** in §3–§4 are computed from the 500 jsonl records unless noted.

This file is the comparison-ready write-up: methodology first (so the three backends are not mixed), then results, then a systematic Doris error analysis.

| Engine | Run ID | Eval contract | Headline EX / 500 |
|--------|--------|---------------|------------------:|
| SQLite | `aws_20260809_studyparity_full` | **Same-engine** (gold + pred on SQLite) | **0.536** (268/500) Strict |
| Postgres | `aws_20260809_studyparity_postgres` | **Same-engine** (gold + pred on Postgres) | **0.420** (210/500) Strict |
| **Doris** | **`doris_20260815_113514`** | **Cross-engine dual-DSN** (gold on Postgres, pred on Doris) | **0.42** (210/500) overall; **0.468** (210/449) among `dual_ok` |

Read **overall EX** next to SQLite/Postgres **Strict EX**. Read **EX among `dual_ok`** as the Doris-fair number (both engines returned a result set). Do not compare Doris `dual_ok` EX to Postgres **scored** EX 0.609 — that 0.609 drops 148 Postgres `eval_error` rows, most of them gold SQLite-isms.

---

## 1. Methodology (reproducible)

### 1.1 Hardware and roles

Doris experiments use the four-role `doris-test-*` cluster. Generation talks to LangChain on **nl2sql**; vLLM serves Arctic on **gpu**; BIRD gold lives on Postgres on **db**; predicted SQL is executed on Apache Doris (MySQL protocol) on **analytics** (Kafka / Debezium / routine loads into `bird_minidev_olap`).

SQLite and Postgres baselines use the three-role `nl2sql-comparison-*` cluster (db + gpu + nl2sql). Same model binary and vLLM serving path; no analytics/Doris hop.

Scoring for Doris is **not** done on the nl2sql host. Gold Postgres is unreachable from nl2sql under the default security group. The harness runs on the **laptop** through tunnels:

| Role | Local tunnel | Remote |
|------|--------------|--------|
| Gold Postgres | `127.0.0.1:55433` | db `:5432` (`search_path` = `db_id`) |
| Pred Doris | `127.0.0.1:9031` | analytics FE `:9030` / `bird_minidev_olap` |
| LangChain API | `127.0.0.1:8011` | nl2sql `:8011` |

Scoring gold from nl2sql yields connection timeouts and opaque EX=0. Preflight: `scripts/aws/preflight-eval-health.ps1`. Profile: `experiments/profiles/arctic-vllm-studyparity-doris-full.json`.

### 1.2 Shared generation knobs (apples-to-apples)

Held fixed across SQLite, Postgres, and Doris unless a row says otherwise:

| Knob | Value |
|------|--------|
| Model | `Snowflake/Arctic-Text2SQL-R1-7B` |
| Serving | vLLM, OpenAI-compatible, temperature 0 |
| Framework | LangChain HTTP API (`mode=api`) |
| Exec in the API | `SQL_EXEC_MODE=skip` — API returns SQL; the harness executes |
| Decoding | OmniSQL SQL-fence **prefill + stop**; repair retries **0** |
| Evidence | on (BIRD evidence string in the prompt) |
| Timeout / workers | **10 s** client timeout, **2** workers |
| Schema | `SCHEMA_SOURCE=bird_tables`: **one `db_id`** `CREATE TABLE` text from BIRD `dev_tables.json` |
| Schema link | BM25 top_k=8 + FK (`schema_selector_mode=bm25`) |
| Suite | BIRD minidev **full**, N=500 |
| EX cell match | `--ex-mode bird`: positional set of tuples, **ignore aliases**, unequal column counts → EX=false |

Prompt dialect is the one difference that is *supposed* to change:

| Backend | `arctic_sql_dialect` | “Database Engine:” line | Where pred SQL runs |
|---------|---------------------|-------------------------|---------------------|
| SQLite | `sqlite` | SQLite | SQLite minidev files |
| Postgres | `postgresql` | PostgreSQL | Postgres `bird` |
| Doris | `mysql` | Apache Doris (MySQL) | Doris MySQL `:9030` |

### 1.3 Doris-only: dialect prompt + universal compiler

Fair Doris generation is **OmniSQL MySQL instructions + a universal SQLite→MySQL compiler**. There are **no per-question patches** (no hardcoded qids, evidence strings, or named BIRD columns).

The mysql dialect prompt (`MYSQL_DIALECT_INSTRUCTIONS` + fence prefill) *demands* `DATE_FORMAT` / `CONCAT` / `NOW` / backticks and forbids `strftime`, `||`, `datetime('now')`.

`sql_guard` then applies mechanical rewrites that work on any SQL:

- `strftime(fmt, expr)` → `DATE_FORMAT(expr, fmt)`
- `a || b` → `CONCAT(a, b)`
- `datetime('now')` / `date('now')` / `time('now')` → `NOW()` / `CURDATE()` / `CURTIME()`
- `IIF` → `IF`
- `"ident"` → `` `ident` `` (Doris treats double quotes as strings)
- backtick reserved FROM/JOIN tables: `match`, `sets`, `order`, `event`
- CDC parenthesis sanitizer on backticked idents; unquoted identifiers folded to lowercase
- `col = (SELECT …)` → `col IN (SELECT …)` (Doris `SCALARSUBQUERY` / `Expected EQ 1`)

Jsonl stores **post-guard** `pred_sql`. A stored `DATE_FORMAT` may be model-native or compiled from `strftime`; we cannot split those from the file. We *can* say that **no `strftime` and no `||` reached Doris** on this run (0 occurrences in the 500 stored preds).

### 1.4 Dual-DSN scoring (gold = Postgres, pred = Doris)

Gold SQL is BIRD minidev gold, executed on **Postgres**. Predicted SQL is generated for Doris/MySQL and executed on **Doris**. Wrapper: `SELECT * FROM (<sql>) AS _bird_q LIMIT 500`.

| Flag | Meaning |
|------|---------|
| `n_api_ok` | API returned SQL within 10 s (not timeout / HTTP 400) |
| `n_gold_ok` | Gold executed on Postgres |
| `n_pred_ok` | Pred executed on Doris |
| `n_dual_ok` | `gold_ok` ∧ `pred_ok` |
| **EX among `dual_ok`** | bird EX on rows where both engines returned a result set |
| **EX overall** | EX-true count / 500 (API/gold/pred failures count as 0) — comparable to SQLite/Postgres **Strict EX** |
| `soft_f1` | Mean among `dual_ok` (not among all 500) |

API / gold / pred failures are **not** scored as soft_f1=0 “true zeros”; they are excluded from `ex_among_dual_ok`.

**Same-engine vs dual-DSN (do not mix these):**

| | SQLite / Postgres baselines | Doris |
|--|-----------------------------|--------|
| Gold engine | Same as pred | **Postgres** |
| Pred engine | SQLite or Postgres | **Doris** |
| Headline / 500 | Strict EX = (ex==1)/n | EX overall = (ex==1)/n |
| Conditional rate | **Scored EX** = mean over rows with pred and no `eval_error` | **EX among `dual_ok`** |
| What scored/dual_ok drops | Timeouts + eval failures (on Postgres: mostly **gold** SQLite-isms) | API + gold + pred failures |

Postgres scored EX **0.609** (210/345) is high because 148 `eval_error` rows are excluded, and ~110 of those are gold SQLite dialect on Postgres. Doris gold almost always runs (Postgres is the native gold engine: 487/488 api_ok). Comparing 0.609 to Doris 0.468 is invalid.

bird EX ignores column aliases. Postgres unnamed columns arrive as `?column?` / `sum`; Arctic usually aliases (`ratio`, `percentage`). Jsonl persists `n_rows_*`, `n_cols_*`, `gold_columns`, `pred_columns`, and `alias_mismatch` when names differ but cells match. **Cell values are not stored** — offline split of “wrong number” vs “numeric format” vs CDC requires a live re-exec.

### 1.5 Why LLM-judge is not the primary metric

`eval_mode=dual_dsn_llm_judge` (`judge_equiv_v1`, temperature=0) was tried on diverse10 with **the same Arctic Text2SQL model** as judge (`doris_20260814_113124`, `doris_20260813_083653`). All judged rows **abstained**: `judge_parse_error: no JSON object` — Arctic emitted another SQL walkthrough instead of `{equivalent, confidence, rationale}`. Until a non-Text2SQL judge is pinned, **bird EX among `dual_ok`** is the headline cross-engine metric, and **EX overall** is the Strict-style headline for three-way tables.

Reproduce the primary Doris run:

```powershell
cd doris-test
.\scripts\aws\write-ssh-config.ps1
.\scripts\aws\preflight-eval-health.ps1
.\scripts\aws\run-benchmark-aws.ps1 `
  -Profile experiments/profiles/arctic-vllm-studyparity-doris-full.json
```

SQLite / Postgres baselines: `aws/nl2sql-comparison` profiles `arctic-vllm-onepass-10s-full.json` and `arctic-vllm-studyparity-postgres-full.json`; campaign write-up `experiments/arctic-vllm-onepass-10s.md`.

---

## 2. Experiment log (Doris gates)

Same Arctic + vLLM + dual-DSN unless noted.

| Run | Suite | api_ok | gold_ok | pred_ok | dual_ok | EX among dual_ok | EX / n | Notes |
|-----|-------|-------:|--------:|--------:|--------:|-----------------:|-------:|-------|
| `doris_20260814_113124` | diverse10 | 9 | 9 | 4 | 4 | 0.000 | 0.000 | Live mixed catalog; unknown-table; Arctic-as-judge abstains 4/4 |
| `doris_20260814_170306` | diverse10 | 9 | 9 | 8 | 8 | 0.125 (1/8) | 0.100 | **`bird_tables` + qualify**; unknown-table gone; jsonl lacks bird cell metadata |
| `doris_20260814_201420` | **full** | 487 | 486 | 382 | 381 | 0.472 (180/381) | **0.36** | Study-parity + bird EX; **no** dialect compiler |
| **`doris_20260815_113514`** | **full** | **488** | **487** | **450** | **449** | **0.468 (210/449)** | **0.42** | Dialect **prompt + universal compiler** |

Diverse10 qids that illustrate the catalog fix (`113124` → `170306` / full):

| qid | db_id | Pre-parity (`113124`) | After `bird_tables` (still true on `113514`) |
|-----|-------|------------------------|-----------------------------------------------|
| 17 | california_schools | Unknown table `california_schools` | Executes; EX still false (RANK vs AVG) |
| 1375 | student_club | Unknown table `student_club` | **EX=true** |
| 760 | superhero | Unknown table `card_games` (wrong db) | **EX=true** |
| 219 | toxicology | Unknown column `bond_type` (wrong db) | Executes; EX false |
| 875 | formula_1 | SCALARSUBQUERY on `year = (SELECT …)` | IN rewrite; **EX=true** |
| 1481 | debit_card_specializing | timeout | Still **timed out** at 10 s |

Do not treat `170306` EX=0.125 as a bird-EX number (no `ex_mode` / column counts in that jsonl).

---

## 3. Results

### 3.1 Three-way comparison (full minidev 500)

| Engine | Run | Headline EX / 500 | Conditional EX | Timeouts | Exec failures | soft_f1 | latency_ms mean |
|--------|-----|------------------:|---------------:|---------:|--------------:|--------:|----------------:|
| SQLite | `aws_20260809_studyparity_full` | **0.536** (268/500) Strict | 0.562 (268/477) scored | 5 (~1%) | 18 eval_error | 0.580 scored | 3629 |
| Postgres | `aws_20260809_studyparity_postgres` | **0.420** (210/500) Strict | 0.609 (210/345) scored | 7 (1.4%) | **148** eval_error (mostly **gold** SQLite-isms) | 0.624 scored | 3614 |
| **Doris dual-DSN** | **`doris_20260815_113514`** | **0.42** (210/500) overall | **0.468 (210/449)** among `dual_ok` | 10 (2%) + 2 HTTP 400 | **38 pred** + 1 gold | 0.490 among `dual_ok` | 3839 |

How to read this:

- **Overall / Strict EX** is the only /500 number that is comparable across the three engines. Doris **0.42** now **matches** same-engine Postgres Strict **0.420** (same 210/500 count; not the same 210 questions). It remains **11.6 pp** below SQLite **0.536**.
- **Doris EX among `dual_ok` 0.468** sits **between** Postgres Strict (0.420) and SQLite Strict (0.536). It is the fair cross-engine rate once both engines return rows. It is **not** comparable to Postgres scored 0.609.
- Latency is in the same band (~3.6–3.8 s mean). Timeouts stay ~1–2% under the 10 s / fence-prefill contract.
- 90 Doris rows are `alias_mismatch` (names differ, cells match); all 90 are EX=true under bird. Those would have been EX=false under `strict`.

### 3.2 Doris run history (compiler off → on)

| Metric | `201420` (no compiler) | **`113514` (prompt + compiler)** |
|--------|-----------------------:|---------------------------------:|
| n_api_ok | 487 | **488** |
| n_gold_ok | 486 | **487** |
| n_pred_ok | 382 | **450** |
| n_dual_ok | 381 | **449** |
| EX among dual_ok | 0.472 (180/381) | **0.468 (210/449)** |
| EX overall | 0.36 (180/500) | **0.42 (210/500)** |
| soft_f1 among dual_ok | 0.495 | 0.490 |
| latency_ms mean | 3646 | 3839 |
| alias_mismatch | 68 | 90 |
| pred_fail | 105 | **38** |
| `strftime` in pred_sql / pred_err | 42 / 34 | **0 / 0** |
| `\|\|` in pred_sql | 4 | **0** |
| `DATE_FORMAT` in pred_sql | — | **46** |
| MATCH/SETS pred_err | 24 | **0** (jsonl; see §4.6) |

Overall EX rose because **68 extra questions now execute** on Doris (+30 net EX-true: 42 newly true, 12 lost). EX among `dual_ok` ticked **down** 0.472 → 0.468: the newly executable rows are disproportionately generation-wrong, so they dilute the conditional rate while lifting the Strict headline.

### 3.3 Funnel — `doris_20260815_113514`

```
N = 500
 ├─ API fail ………… 12   (10 timed out @10s, 2 HTTP 400)
 ├─ gold fail ………… 1    (qid 930 formula_1: PG “more than one row returned by a subquery”)
 ├─ pred fail ………… 38   (Doris exec; gold was OK)
 ├─ dual_ok, EX=false … 239
 └─ dual_ok, EX=true … 210   ← 0.468 of dual_ok, 0.42 of N
```

| Stage | Count | Drop |
|-------|------:|------|
| Questions | 500 | — |
| api_ok | 488 | −12 |
| gold_ok | 487 | −1 |
| pred_ok | 450 | −37 vs gold_ok among api_ok; 38 pred fails with gold_ok |
| dual_ok | 449 | −1 (qid 930: pred_ok but gold_ok false) |
| EX=true | 210 | −239 semantic / shape / residual data |

### 3.4 Per `db_id` (latest run)

EX = true count. Rates are EX/n and EX/`dual_ok`.

| db_id | n | pred_fail | dual_ok | EX | EX/n | EX/dual_ok | vs `201420` EX |
|-------|--:|----------:|--------:|--:|-----:|-----------:|----------------|
| superhero | 52 | 0 | 52 | 40 | **0.769** | 0.769 | 39 → 40 |
| student_club | 48 | 1 | 47 | 30 | **0.625** | 0.638 | 30 = |
| european_football_2 | 51 | 3 | 47 | 25 | **0.490** | 0.532 | 16 → 25 (MATCH recovered exec) |
| toxicology | 40 | 2 | 38 | 19 | 0.475 | 0.500 | 20 → 19 |
| formula_1 | 66 | 8 | 54 | 27 | 0.409 | 0.500 | 25 → 27 |
| codebase_community | 49 | 3 | 45 | 20 | 0.408 | 0.444 | 17 → 20 |
| thrombosis_prediction | 50 | 11 | 37 | 19 | 0.380 | 0.514 | 9 → 19 (`strftime` recovered) |
| card_games | 52 | 3 | 49 | 14 | 0.269 | 0.286 | 9 → 14 (`sets` recovered) |
| debit_card_specializing | 30 | 0 | 28 | 8 | 0.267 | 0.286 | 9 → 8 |
| financial | 32 | 0 | 31 | 8 | 0.250 | 0.258 | 6 → 8 |
| **california_schools** | 30 | 7 | 21 | **0** | **0.000** | **0.000** | 0 = (dual_ok 13 → 21, still 0 EX) |

`european_football_2` overall was weak on `201420` because of 11 unquoted `match` syntax fails; among queries that execute, EX stays ~0.53. `california_schools` still has **zero** EX-true among 21 executable questions — that is generation / spaced-column quoting / window semantics, not `strftime`.

---

## 4. Systematic Doris error analysis (`113514` jsonl)

Primary class from `api_error` / `gold_error` / `pred_error` / shape metadata. Mutually exclusive. Examples are 3–5 qids with shortened SQL; this is not a dump of 500 rows.

### 4.1 API fail (12) — timeout and HTTP 400

**Timeout (10):** client 10 s budget, empty `pred_sql`. Same gate as the Aug 9 SQLite/PG campaign (~1–2%).

| qid | db_id | latency_ms |
|-----|-------|----------:|
| **1481**, **1482** | debit_card_specializing | ~10010 |
| **1149**, **1185** | thrombosis_prediction | ~10010 |
| **1115** | european_football_2 | 10010 |
| **880**, **944**, **955** | formula_1 | ~10010 |
| **36** | california_schools | 10004 |
| **94** | financial | 10006 |

Hard questions (1481 family, Landon Donovan %, F1) still empty. **880** was EX=true on `201420` and timed out here (one of 12 net EX losses). **1149** executed on `201420` (extra-column EX=false) and now times out. **32** timed out on `201420` and now produces SQL that fails syntax (§4.3).

**HTTP 400 (2):** guard/API reject, no SQL. qids **539** (`codebase_community`), **41** (`california_schools`). Bodies are not in jsonl. **94** was HTTP 400 on `201420` and is a timeout here.

### 4.2 Gold error (1)

qid **930** (`formula_1`): BIRD gold uses a scalar subquery that returns multiple rows on Postgres (`more than one row returned by a subquery used as an expression`). Pred still executed (`pred_ok`); not `dual_ok`. Unchanged vs `201420`.

### 4.3 Pred-error taxonomy (38)

Gold was OK. Unknown table: **0**. `strftime` pred_err: **0**. MATCH/SETS pred_err: **0**.

| Class | n | % of 38 | Engine vs generation | Signal |
|-------|--:|--------:|----------------------|--------|
| **unknown column** | **12** | 31.6% | missing JOIN / wrong table / CDC names | `Unknown column '…'` |
| **GROUP BY / select-list** | **10** | 26.3% | SQLite-loose GROUP BY | `not produced by aggregation output` |
| **syntax** (unquoted spaced names) | **4** | 10.5% | quoting | `Encountered: COUNT\|YEAR\|NAME\|IDENTIFIER` |
| **scalar subquery leftover** | **3** | 7.9% | rewrite gap | `SCALARSUBQUERY` / `Expected EQ 1` in SELECT list |
| **group_concat type** | **2** | 5.3% | Doris types | `group_concat requires … STRING` |
| **avg on text** | **2** | 5.3% | missing CAST | `avg requires a numeric parameter` |
| **correlated agg subquery** | **2** | 5.3% | Doris planner | `Unsupported correlated subquery with grouping` |
| **ambiguous column** | **1** | 2.6% | generation | `Column 'diagnosis' … is ambiguous` |
| **other dialect** (`date_extract`) | **1** | 2.6% | leftover PG-ish fn | `date_extract(datev2, varchar)` |
| **pred exec timeout** | **1** | 2.6% | heavy JOIN | `Query timeout` |

#### Unknown column (12)

By `db_id`: `thrombosis_prediction` 6, `california_schools` 4, `codebase_community` 2.

| qid | Error | Interpretation |
|-----|-------|----------------|
| **1252** | `Unknown column 'igg' in 'table list'` | `igg` lives on `laboratory`; pred filtered `examination` only — **missing JOIN** |
| **1254** | `Unknown column 'first_date'` | CDC/quote: gold `"First Date"`; pred used unquoted `first_date` |
| **1256** | `Unknown column 'crp'` | `crp` is on `laboratory`, not `patient` |
| **23** | `Unknown column 'school' in 'frpm'` | spaced FRPM / `School Name` |
| **595** | `Unknown column 'postid' in 'ph'` | wrong alias / missing join on post history |

#### GROUP BY / select-list (10)

SQLite-tolerant `GROUP BY pk` while selecting other columns. Doris (like Postgres) rejects it. qids: **1381** `student_club`; **1168** `thrombosis_prediction`; **1098** `european_football_2`; **846, 897, 994** `formula_1`; **349, 518** `card_games`; **231, 327** `toxicology`.

```sql
-- 1381: GROUP BY m.member_id but SELECT first_name, last_name
select m.first_name, m.last_name from student_club.member m
join student_club.attendance a on m.member_id = a.link_to_member
group by m.member_id …
```

Gold for 1381 already lists those columns in GROUP BY. This is generation, not a missing compiler rule.

#### Syntax (4) — spaced identifiers without backticks

| qid | db_id | Fragment |
|-----|-------|----------|
| **32** | california_schools | `select school name, (frpm count (k-12) / enrollment (k-12))` |
| **72** | california_schools | `f.academic year = '2014-2015'` |
| **77** | california_schools | `frpm.county name = 'Los Angeles'` |
| **1179** | thrombosis_prediction | `e.acl igm > 0` (gold `"aCL IgM"`) |

The compiler rewrites `"ident"` → backticks and sanitizes *already-backticked* CDC names. It does not invent backticks for a bare `school name` token sequence. That would be a parser, not a universal rewrite.

#### Scalar subquery leftover (3)

IN rewrite only fires for `ident = (SELECT …)`. These are **scalars in the SELECT list**:

| qid | Pattern |
|-----|---------|
| **1094** | `(SELECT overall_rating …) - (SELECT overall_rating …)` |
| **1134** | `(SELECT jumping WHERE id = 6) - (SELECT jumping WHERE id = 23)` |
| **459** | `CASE WHEN (SELECT convertedmanacost …) > (SELECT …)` |

Same three qids as `201420`.

#### Other dialect / types (8)

| qid | Error |
|-----|-------|
| **1225**, **967** | `group_concat` needs STRING (`group_concat(DISTINCT p.id)`, `group_concat(… number …)`) |
| **960**, **988** | `avg` on text (`fastestlapspeed`, `duration`); gold `CAST … AS NUMERIC` |
| **1001**, **1014** | unsupported correlated subquery with aggregation |
| **1175** | ambiguous `diagnosis` |
| **1171** | `date_extract(birthday, '%Y')` — not MySQL `DATE_FORMAT` / `YEAR` |
| **639** | Doris **query timeout** on `posts.tags like concat('%', t.tagname, '%')` |

### 4.4 Dual-ok but EX=false (239)

Shape metadata exists; cells do not. Classes are **shape heuristics**.

| Shape class | n | % of 239 | Likely cause |
|-------------|--:|---------:|--------------|
| Same shape, **no tuple overlap** (soft_f1=0) | **123** | 51% | Semantic NL2SQL, or numeric/NULL/CDC (see clones) |
| **Row-count** mismatch (cols equal, not LIMIT-capped) | **63** | 26% | Extra/missing JOIN, DISTINCT, filters, grain |
| **Extra columns** (pred has more cols than gold) | **24** | 10% | SELECT the answer **and** the ranking aggregate |
| **Missing columns** | **11** | 5% | Dropped a requested field |
| **LIMIT 500 cap** (gold or pred rows = 500) | **9** in this exclusive class; **20** EX=false dual_ok hit the cap overall | | Harness wrapper |
| Same shape, **partial overlap** (soft_f1>0) | **9** | 4% | Near-miss filters / extras |

**Extra columns (bird EX correctly 0):**

| qid | Gold cols | Pred cols | Question asks for |
|-----|-----------|-----------|-------------------|
| **1479** | 1 year | `year`, `totalconsumption` | *which year* — not the sum |
| **1480** | 1 month | `month`, `totalconsumption` | *peak month* |
| **1531** | 3 | 4 | top spender + avg price + currency — pred added `totalspent` |

**Wrong grain (row_count):**

| qid | Gold rows | Pred rows | Note |
|-----|----------:|----------:|------|
| **1322** | 4 | 1 | Gold: count **per** qualifying event; pred: one total |
| **1501** | 2 | 0 | Pred `DATE_FORMAT` on a YYYYMM text/`date` join; empty set |
| **1524** | 1 | 0 | Pred selected `segment` instead of gas-station `country` |

**LIMIT 500:** 20 EX=false `dual_ok` rows have `n_rows_gold=500` or `n_rows_pred=500`. Example **1500**: gold 500 vs pred 27 (`DISTINCT`); **1088** both capped at 500, soft_f1=0.47.

**Candidate CDC / type mismatch (not proven — no persisted cells).** Same predicate, 1×1, soft_f1=0:

```sql
-- 1483 gold (PG)
SELECT SUM(Consumption) FROM yearmonth
WHERE CustomerID = 6 AND Date BETWEEN '201308' AND '201311'

-- 1483 pred (Doris)
SELECT SUM(consumption) AS totalconsumption FROM debit_card_specializing.yearmonth
WHERE customerid = 6 AND date BETWEEN '201308' AND '201311'
```

Also **1361** / **1380** / **1409** (`student_club` pizza / food / 2019-08-20 sums) and **356** (`card_games` `power = '*'`). Possible: DATE vs YYYYMM text, NULL vs 0, Decimal normalization, or CDC row drift. **Cannot decide without cells or a live re-exec.** There are **101** same-shape 1×1 EX=false rows; most are ordinary semantic errors (e.g. **1472** least consumption in LAM: pred never joined `customers.segment`).

**Semantic generation (majority of 239):** wrong JOIN/grain/SELECT list. **17** gold `RANK() OVER (ORDER BY AvgScrWrite)` vs pred `AVG … GROUP BY CharterNum`. **1476** 1×1 CAST/`DATE_FORMAT` on YYYYMM. These also exist on SQLite/PG.

### 4.5 Residual vs `201420` (what the compiler actually fixed)

Pairwise on the same 500 qids:

| | Count |
|--|------:|
| Pred-exec recovered (`201420` fail → `113514` ok) | **74** |
| of those, now EX=true | **29** |
| of those, execute but EX=false | **45** |
| Still pred-fail | 31 |
| New pred-fail (executed before, fail now) | 7 |
| Net new EX-true | 42 − 12 lost = **+30** |

Recovered pred-exec by **old** error class:

| Old class | Recovered |
|-----------|----------:|
| `strftime` | **32** (of 34) |
| MATCH/SETS | **24** (of 24) |
| unknown column | 15 |
| syntax | 2 |
| other | 1 |

Evidence the compiler/prompt worked:

- Stored pred_sql: **`strftime` 42 → 0**, **`||` 4 → 0**, **`DATE_FORMAT` 46**, **`CONCAT` present**.
- **1025** `european_football_2.match` now `` join … `match` m `` and **EX=true**.
- **405** `` card_games.`sets` `` now **pred_ok** (EX still false — generation).
- **1150** / **1162** thrombosis dates: `strftime` → `date_format`, **EX=true**.
- **1156** `Unknown column 'ID' in 'Patient'` → lowercase `patient.id`, **EX=true**.

The run summary listed MATCH/SETS **24 → 1 MATCH**. Jsonl on `113514` has **zero** `Encountered: MATCH|SETS` in `pred_error`. All 11 preds that mention `match` execute (backticked). Treat leftover MATCH as **0** from the records.

New pred-fails (generation drift, not compiler regression): **846, 994** GROUP BY; **967** `group_concat`; **595, 604** unknown column; **231** GROUP BY; **32** spaced FRPM syntax (was API timeout).

EX losses include timeout **880** and several `ex_mismatch` flips (`1473`, `1533`, …) — expected one-pass variance, not a dialect undo.

### 4.6 Residual: model vs dialect vs scoring vs CDC

| Bucket | Where it still bites | What it is |
|--------|----------------------|------------|
| **Model semantics** | Most of 239 EX=false; california_schools **0/30**; extra SELECT columns; SQLite GROUP BY (10) | Arctic NL2SQL quality; also present on SQLite/PG |
| **Remaining dialect** | 38 pred_fail: spaced names, SELECT-list scalars, `avg`/text, `group_concat`, `date_extract`, correlated agg | Not `strftime`/`MATCH`/`||`. Further *universal* compilers possible; not qid patches |
| **Scoring** | 90 alias_mismatch **recovered** by bird EX; LIMIT 500 (20 rows); no cell persistence | Dual-DSN harness |
| **API** | 12 | 10 s / HTTP 400 |
| **CDC / data** | Unquantified; identical-SQL clones (1483, 1361, …) | Need live re-exec or persisted cells |

---

## 5. Limitations

1. **Cross-engine vs same-engine.** Doris gold is Postgres; SQLite/PG gold is the same engine as pred. Overall/Strict EX is the comparable /500 headline. `dual_ok` EX is Doris-fair and must not be lined up with Postgres scored 0.609.
2. **No cell persistence.** Cannot offline-split numeric format vs wrong number vs CDC. Re-score needs live tunnels (`EXPERIMENTS.md`).
3. **Jsonl is post-guard.** Prompt vs compiler contribution to `DATE_FORMAT` cannot be split from this file.
4. **LIMIT 500** on both engines. Large set-valued answers are truncated.
5. **10 s / repair 0.** Fair vs the Aug 9 study-parity campaign; not a max-EX sweep.
6. **LLM-judge unused** on the 500. Diverse10 proved Arctic-as-judge cannot emit `judge_equiv_v1` JSON.
7. **california_schools** remains 0 EX after the compiler. That is not a dialect-headline problem anymore.

---

## 6. What a comparison should cite

Use these three numbers together, never one in isolation:

1. **SQLite Strict EX 0.536** — `aws_20260809_studyparity_full`, same-engine, bird EX, N=500.  
2. **Postgres Strict EX 0.420** — `aws_20260809_studyparity_postgres`, same-engine, bird EX, N=500. Scored 0.609 is a footnote about gold SQLite-isms, not the headline.  
3. **Doris overall EX 0.42** and **Doris EX among `dual_ok` 0.468** — `doris_20260815_113514`, gold=PG / pred=Doris, bird EX, dialect prompt + universal compiler, N=500.

Previous Doris full run without the compiler: `doris_20260814_201420`, overall **0.36**, `dual_ok` **0.472**, pred_ok **382**. The compiler did not raise conditional EX; it raised executable coverage and the Strict headline to Postgres parity.

Older narrative for `201420` only: [`arctic-vllm-doris-minidev-analysis.md`](arctic-vllm-doris-minidev-analysis.md) (superseded as the comparison source).
