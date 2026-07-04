# Puppet Dashboard

Puppet Dashboard is an agentic analytics app: a natural-language analyst that can inspect connected PostgreSQL data, run safe queries, and turn the answer into one or more useful dashboard views.

The Dota 2/U.GG-style experience is the demo vertical. The bigger idea is broader: connect finance, sales, product, operations, or game data and let an analyst ask questions in plain English while the app checks the schema, queries the data, explains the answer, and builds the right charts.

## What it does now

- Provides a U.GG/OP.GG-inspired Dota meta hub with hero selector, counters, synergies, trend cards, sample-size context, and live query links.
- Answers Dota questions through deterministic analytics paths when correctness matters, for example counters, draft pairings, and hero pick trends.
- Uses an LLM as an analyst layer for flexible SQL generation, result explanation, and chart planning.
- Introspects the live PostgreSQL schema so the same backend can answer questions over other relational datasets.
- Supports local Ollama/Qwen or hosted OpenRouter models.
- Includes a safe OpenDota enrichment pipeline with rate-limit delays, resumable imports, and a homepage button to trigger refresh/backfill jobs.

## Architecture

The app intentionally separates trusted metrics from LLM reasoning:

1. The backend introspects the live PostgreSQL schema.
2. For known Dota analytics, deterministic SQL views answer the question directly.
3. For general datasets, the LLM receives the schema context and writes read-only SQL.
4. SQL is validated, executed with a timeout, and repaired once if the database returns an error.
5. The result shape is profiled.
6. The chart planner selects multiple charts when the data supports more than one useful view.
7. The analyst readout explains the result while preserving sample-size and reliability warnings.

This is the intended production shape: certified metric/view logic for important business questions, plus an LLM to route messy user intent, summarize findings, and assemble dashboards.

## Local development

Start Ollama first if you want the local model path:

```powershell
ollama pull qwen3:8b
ollama serve
```

Start the Flask API:

```powershell
$env:FLASK_PORT='5001'
$env:LLM_PROVIDER='ollama'
$env:OLLAMA_MODEL='qwen3:8b'
.\venv\Scripts\python.exe backend\server.py
```

Start the Next.js app:

```powershell
npm run dev -- --hostname 127.0.0.1 --port 3001
```

Open [http://127.0.0.1:3001](http://127.0.0.1:3001).

The frontend API routes try the backend on port `5001` first and then fall back to `5000`.

## Environment variables

Create a local `.env` for PostgreSQL and optional model providers:

```text
POSTGRES_DB=...
POSTGRES_USER=...
POSTGRES_PASS=...
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen3:8b
OLLAMA_API_URL=http://127.0.0.1:11434/api/chat

# Optional hosted fallback
OR_API_KEY=...
OPENROUTER_MODEL=...

# Optional OpenDota quota
OPENDOTA_API_KEY=...
```

`LLM_PROVIDER=auto` will try Ollama first and fall back to OpenRouter when configured.

## Dota data pipeline

The homepage has an "Enrich database" panel with safe presets. The same jobs can be run manually:

```powershell
# Enrich matches already stored in PostgreSQL.
.\venv\Scripts\python.exe backend\ingest_opendota.py --enrich-db-existing-only --delay 1.2 --max-api-calls 1500

# Small recent refresh.
.\venv\Scripts\python.exe backend\ingest_opendota.py --days 30 --matches-per-week 25 --delay 1.2 --max-api-calls 1500

# Larger yearly backfill.
.\venv\Scripts\python.exe backend\ingest_opendota.py --days 385 --matches-per-week 75 --delay 1.2 --max-api-calls 6000
```

The importer is designed to be rerun safely:

- it upserts matches;
- replaces player rows only for the match being refreshed;
- commits after every match;
- skips already-enriched rows when possible;
- honors OpenDota `429` retry windows;
- uses a configurable delay so a long import does not break midway from rate limiting.

## Dota analytics views

`backend/analytics.sql` defines the demo metric layer:

- `hero_performance_scores`: reliability-adjusted hero performance.
- `player_match_facts`: enriched player facts with side and win/loss attribution.
- `hero_matchups`: counter candidates by observed win rate, matchup score, and sample size.
- `hero_synergies`: ally pairings by observed win rate, synergy score, and sample size.
- `team_comps`: five-hero lineups and outcomes.
- `hero_item_usage`: item usage and observed win rate by hero.

The API exposes coverage and reliability so weak data is not presented as certain. Current Dota recommendations may be exploratory until enough matches are imported for each hero/pairing.

## API endpoints

- `GET /health` - backend/database/model status, including Ollama availability.
- `POST /sql-query` - natural-language query to SQL, deterministic Dota route, chart plan, and analyst explanation.
- `GET /meta-dashboard?hero=Axe` - homepage meta hub data for a selected hero.
- `POST /import/start` - starts one safe import preset: `recent`, `backfill`, or `enrich-existing`.
- `GET /import/status` - current import job status and recent log tail.

## Testing

Useful local checks:

```powershell
npx tsc --noEmit
.\venv\Scripts\python.exe -m py_compile backend\server.py backend\ingest_opendota.py
```

Smoke-test user questions through the app:

- `what counters Axe in Dota 2?`
- `what heroes work best with Axe?`
- `How often was Axe picked by month?`
- `show revenue by month` after connecting a financial dataset with matching tables.

## Production direction

To become truly production-scale for arbitrary data, the next layer should be a dataset registry:

- business-friendly table and column descriptions;
- certified metric definitions such as revenue, margin, churn, win rate, or matchup score;
- data freshness and coverage checks;
- role-based permission rules;
- approved dashboard templates;
- query audit logs and evaluation sets.

The current codebase already has the skeleton for that: schema introspection, read-only SQL execution, deterministic metric views, LLM-based interpretation, and multi-chart dashboards.
