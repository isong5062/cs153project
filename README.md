# Trading Bot

AI-driven paper trading bot for US equities. LLM-orchestrated hybrid: classical quant signals + specialist Claude agents + a reflection loop that proposes strategy changes which must earn their way through a backtest tournament before touching paper trades.

Design doc: [`C:\Users\violi\.claude\plans\ticklish-twirling-wozniak.md`](../.claude/plans/ticklish-twirling-wozniak.md)

---

## Status

Phase 2 — broker + paper-trading loop (rule-based, no LLMs yet). See design doc §15 for the full staged rollout.

---

## Quickstart (local dev)

Prereqs: Python 3.11+, Docker Desktop, [uv](https://docs.astral.sh/uv/).

```bash
# 1. Copy env and fill in Alpaca + Anthropic keys
cp .env.example .env

# 2. Start Postgres + Redis
docker compose up -d

# 3. Install deps (creates .venv)
uv sync --all-extras

# 4. Apply DB migrations
uv run alembic upgrade head

# 5. Backfill 5 years of daily bars for the default universe
uv run python -m scripts.seed_bars

# 6. Run tests
uv run pytest
```

---

## Layout

See design doc §13 for the full target layout. Phases 0–1 deliver:

- `src/config.py` — typed settings
- `src/persistence/` — SQLAlchemy models + session
- `src/data/providers/` — Alpaca + yfinance
- `src/signals/strategies/` — `Strategy` protocol + 3 baselines (mean-reversion, trend-following, breakout)
- `src/backtest/` — vectorbt runner, walk-forward, Monte Carlo, tournament
- `scripts/seed_bars.py` — universe backfill
- `scripts/run_tournament.py` — run the leaderboard
- `alembic/` — migrations
- `docker-compose.yml` — Postgres + Redis

---

## Safety

`BROKER_MODE` defaults to `paper`. Flipping to `live` takes explicit action. Risk guards (Phase 2) enforce hard limits that LLM agents cannot override.
