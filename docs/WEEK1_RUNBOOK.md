# DB-Navigator AI - Week 1 Runbook

This covers what was built in Week 1, how to run it, and how to measure the
accuracy effect of the self-correction loop. Everything is feature-flagged: with
all flags off, the system runs the documented Config F path unchanged.

## What was built

1. A `pipeline` package holding the framework-agnostic accuracy logic:
   - `flags.py` - `PipelineConfig`, the single source of truth for the feature
     toggles (read from env or per request). Default = Config F baseline.
   - `sql_utils.py` - shared post-processing (`fix_tsql_syntax`), execution,
     JSON-safe serialization, and an order-independent `result_signature`
     (used later by voting).
   - `self_correction.py` - the execution-guided self-correction loop.
   - `engine.py` - `NLToSQLEngine`, the single entry point used by both the API
     and (optionally) the benchmark.
2. A `api` package exposing the engine over FastAPI (`/health`, `/ask`,
   `/correct`, `/feedback`, `/schema`).
3. An additive patch to `evaluation/benchmark.py` that can run the loop during a
   benchmark so the accuracy delta is measured on the same 100-query set.
4. A new `api` service in `docker-compose.yml`, and FastAPI/uvicorn added to
   `requirements.txt`.

## How the self-correction loop works

The loop is a student-written control algorithm; the LLM is one replaceable
component inside it. For each question it generates SQL, executes it, and if
execution fails (or, optionally, returns zero rows) it re-prompts the model with
the failed query, the exact database error, and the retrieved schema context,
asking for a corrected query. It iterates up to a fixed cap (default 2), pinning
the repair temperature low (0.0) for determinism. With `max_iters=0` the loop
performs exactly one generation and one execution, which reproduces the baseline.

## Running the API

From the repo root, with `OPENAI_API_KEY` set in the environment or a `.env`:

```
docker compose up -d mssql postgres
docker compose up api
```

The service builds Vanna once at startup and trains the Config F set if the
ChromaDB store is empty (warm restarts reuse it). Until training finishes
`/health` reports `ready: false` and the other endpoints return 503.

Endpoints:

```
# liveness + active defaults
curl localhost:8000/health

# baseline answer (server defaults)
curl -X POST localhost:8000/ask \
  -H 'content-type: application/json' \
  -d '{"question": "How many active customers are there?"}'

# force the self-correction loop for this one request
curl -X POST localhost:8000/ask \
  -H 'content-type: application/json' \
  -d '{"question": "Top 5 accounts by balance", "self_correction": true, "max_iters": 2}'

# repair a specific query without regenerating
curl -X POST localhost:8000/correct \
  -H 'content-type: application/json' \
  -d '{"question": "...", "sql": "SELECT ...", "error": "Invalid column name ..."}'

# log an accepted answer and add it to training
curl -X POST localhost:8000/feedback \
  -H 'content-type: application/json' \
  -d '{"question": "...", "accepted_sql": "SELECT ...", "helpful": true}'

# schema with inferred relationships (?refresh=true re-runs FK inference)
curl localhost:8000/schema
```

The interactive docs are at `localhost:8000/docs`.

Server-wide defaults are set with `DBNAV_*` env vars (see the `api` service in
`docker-compose.yml`). Per-request fields on `/ask` override them. A request that
sets `voting: true` is rejected with 501 until the voting module ships.

## Running the benchmark with self-correction

The benchmark runs from the host (it uses `app.`-prefixed imports). Baseline,
unchanged:

```
python -m app.evaluation.benchmark --config F
```

With the self-correction loop enabled:

```
python -m app.evaluation.benchmark --config F --self-correct --correct-iters 2
```

New flags: `--self-correct`, `--correct-iters N` (default 2),
`--correct-retry-empty`, `--correct-temperature T` (default 0.0).

The summary prints how many queries triggered a repair and the total repair
iterations, alongside the usual accuracy breakdown by difficulty, category, and
error type.

## Reading the result

Run the two commands above and compare the `Overall` accuracy line. The
documented Config F baseline is 76.0% on gpt-4o-mini. The plan's expectation for
self-correction alone is +3 to +7 points. Per the plan: if the loop alone gives
less than +3 points, debug the repair prompt (in `self_correction.py`) before
moving on to voting. A useful debug run is `--config F --self-correct --limit 20`
on a single difficulty (`--difficulty hard`), since most failures are in the
hard / very-hard buckets and in the value-mapping and missing-JOIN error classes.

## Tests

Unit tests for the loop, the engine, and the SQL helpers run without any
database, LLM, or network (Vanna and the executor are faked):

```
python tests/test_pipeline.py
```

All 21 tests cover: immediate return on success, repair-then-success, the
iteration cap, no-op and non-SQL repair stops, `max_iters=0` matching the
baseline, the `/correct` seed path, retry-on-empty behaviour, repair-temperature
pinning and restoration, engine mode selection, voting rejection, and the SQL
helpers.

## Decisions and things to know

- Indentation: the handoff said tabs, but the real source files use 4 spaces
  with CRLF line endings. The new files follow the real code (4 spaces). If you
  prefer tabs across the codebase, normalise everything in one pass rather than
  mixing.
- Config F descriptions: the Streamlit app does not run the LLM
  `DescriptionGenerator`, but the benchmark's Config F does. The API trains the
  full benchmark Config F set (descriptions included) so its baseline matches the
  documented 76.0% number. Set `DBNAV_API_INCLUDE_DESCRIPTIONS=false` to match
  the Streamlit training set instead.
- Voting is deferred. The config field and the engine seam exist, but enabling
  voting raises until the voting module lands next, following the plan's order
  (measure self-correction first, debug, then add voting).
- The live path (API startup, real LLM repairs) could not be exercised here
  because there is no SQL Server / Postgres / OpenAI access in this environment.
  It was validated by Vanna 0.7.5 source introspection, a FastAPI app-construction
  smoke test, and the 21 unit tests above. Run the benchmark commands to get the
  actual accuracy delta.

## Where the files go in the repo

```
app/pipeline/__init__.py
app/pipeline/flags.py
app/pipeline/sql_utils.py
app/pipeline/self_correction.py
app/pipeline/engine.py
app/api/__init__.py
app/api/schemas.py
app/api/vanna_setup.py
app/api/main.py
app/evaluation/benchmark.py   # patched (additive)
tests/test_pipeline.py
docker-compose.yml            # patched (added api service)
requirements.txt              # patched (added fastapi, uvicorn)
```
