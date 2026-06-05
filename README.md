# Regime Trader

**A self-learning, regime-aware automated trading web app for US equities — built solo for [Stanford CS 153](#) ("The One-Person Frontier Lab").**

Regime Trader reads the overall mood of the stock market with a statistical model, runs trading strategies that you either control by hand or let an AI improve (with your approval), and wraps everything in a hardcoded safety net. It runs entirely on **paper trading** — real live market prices, fake money — so there is zero financial risk.

> ⚠️ **Paper trading only by design.** v1 has *no* real-money code path; a hard guard rejects any non-paper broker config. Educational project — not financial advice.

| | |
|---|---|
| **Project track** | Application / Product · Automation / Agent Systems |
| **Status** | Complete · 78 backend tests + 7 frontend tests passing · lint clean |
| **Stack** | FastAPI · SQLAlchemy · hmmlearn · Next.js 16 · TypeScript · Alpaca (paper) · Anthropic Claude |

---

## Q1 · Why I built this (Problem & Insight)

Running a disciplined trading strategy normally takes a whole **team** — quant researchers, engineers, and risk managers — plus real capital and infrastructure. Everyone else is left with two bad options:

1. **Trade on emotion** — the single biggest reason ordinary investors lose money: buying at the top out of greed, selling at the bottom out of fear.
2. **Hand money to a "black box" bot** they can neither see inside nor control, and can't trust not to blow up.

CS 153's premise is that *one person with the right AI tools can now replace that whole team.* I wanted to test that directly by building a system that is:

- **Adaptive** — it studies its own performance and proposes improvements,
- **Human-controlled** — it can *never* change a running strategy without my explicit approval, and
- **Safe by construction** — a hardcoded risk layer the AI cannot override makes blowing up the account impossible.

The insight is that the hard part isn't predicting the market — it's **discipline and trust**. So the product is built around a single rule: *the human is always in control, and the safety net can never be switched off.*

---

## Q2 · How it works (Execution & Technical Work)

### Architecture

```
┌────────────── Frontend · Next.js / React / TypeScript ──────────────┐
│  Dashboard · Strategies + compare · Manual spec editor · Approvals   │
│  inbox · Alerts · Settings              ↕ REST + WebSocket           │
└──────────────────────────────────────────────────────────────────────┘
                                │
┌────────────── Backend API · FastAPI ───────────────────────────────┐
│  Routers · validation · WebSocket hub · token-budget gate · secrets  │
└──────────────────────────────────────────────────────────────────────┘
        │                                          │
┌───────┴────────┐                    ┌────────────┴──────────────────┐
│  Database       │   ◀── shared ──▶  │  Trading worker (always-on)    │
│  strategies,    │                   │  data → regime → evaluate →    │
│  versions,      │                   │  risk → execute → learn        │
│  proposals,     │                   │  (APScheduler, 5-min loop,     │
│  regimes, risk, │                   │   market-hours gated)          │
│  equity, alerts │                   └────────────┬──────────────────┘
└─────────────────┘                                │
                       ┌───────────────────────────┴────────────────┐
                       │  Alpaca paper account (orders + IEX data)   │
                       │  Anthropic Claude API (proposals, cached)   │
                       └─────────────────────────────────────────────┘
```

**Engine chain:** Data → Regime brain (shared) → Strategy evaluator → Risk clamp → Execution (1 live / N simulated) → Performance → Self-learning proposals → Human approval → new immutable version.

### 1. The shared "regime brain"
The app reads **SPY** (an exchange-traded fund tracking the 500 largest US companies — a proxy for the whole market). A **Hidden Markov Model** — a statistical model that infers a hidden state from observable data — classifies the market's *mood* into one of five **regimes**: `crash`, `bear` (falling/fearful), `neutral`, `bull` (rising/confident), or `euphoria`. The number of regimes is auto-selected by BIC. Online inference uses **forward filtering only**, so a prediction at time *t* can only use data up to *t* — it can never peek at the future. A stability filter suppresses noisy flickering between regimes.

### 2. Strategies are transparent rule tables
A strategy is a validated JSON spec (a small, safe-to-diff DSL). Its heart is `regime_rules`: for each market mood, how much of the portfolio to deploy (**`target_exposure`**, 0–1, the share of money invested vs. held as cash) and a **`max_leverage`** cap (leverage = investing with borrowed money). Every change creates a new **immutable version** (full audit history).

### 3. Two modes
- **Manual** — you have total control; the app never proposes anything. Your edits apply **immediately** and version automatically.
- **Self-learning** — the app drafts improvements from realized profit/loss (an adaptive feedback loop) and from **Claude**, which reads a performance report and proposes deeper spec changes (budget-gated, with prompt caching). **Every AI proposal waits in an Approvals inbox** with a backtest preview until a human approves, rejects, or edits-and-approves it. *Nothing autonomous ever touches a live strategy.*

### 4. One live, many simulated
You can run many strategies at once. They all trade in an internal **simulator** on the same data, but **exactly one** is promoted to trade the real Alpaca paper account. Compare them and promote the winner (the outgoing strategy is flattened first).

### 5. The risk layer is supreme and hardcoded
Independent of the AI, a set of **circuit breakers** (automatic safety switches) clamps every strategy and every proposal — a strategy can only ever be *more* conservative, never looser:

| Trigger | Action |
|---|---|
| −2% on the day | halve position sizes |
| −3% on the day | flatten (sell to cash) |
| −5% on the week | halve position sizes |
| **−10% from peak (drawdown)** | **full stop + requires a manual reset** |

A drawdown stop writes an audit event, fires a **critical alert**, and blocks trading until a human resets it.

---

## Project structure
```
backend/                 FastAPI service + trading engine + worker
  app/
    core/                config, structured logging, paper-only guard
    db/                  SQLAlchemy session + portable JSON column (SQLite/Postgres)
    models/              ORM tables (strategies, versions, proposals, regimes, risk, alerts, …)
    engine/
      data/              Alpaca IEX bars (historical + live stream), market hours
      features/          causal indicators (SMA/EMA/RSI/ATR/vol) + feature engineering
      regime/            GaussianHMM, BIC selection, forward-filter inference, stability filter
      strategies/        spec DSL, deterministic evaluator, immutable versioning
      risk/              hardcoded circuit breakers + clamp (AI-independent)
      execution/         simulator, Alpaca paper executor, 1-live/N-sim router, promotion
      backtest/          walk-forward (no look-ahead), benchmarks, stress tests
      learning/          feedback proposer, Claude proposer, token budget, approval service
      alerts/            persist + log + optional webhook
      loop/              rebalancer + orchestrator (one trading tick)
    api/                 REST routers + WebSocket hub
    seed.py / demo.py    bootstrap a regime / populate demo content (offline-friendly)
    worker.py            APScheduler 5-minute tick entrypoint
  tests/                 78 tests mirroring the engine
frontend/                Next.js 16 App Router + TypeScript + Tailwind + TanStack Query
docker-compose.yml       Postgres + backend + frontend
```

---

## Quick start (reproducible in ~2 minutes, no keys required)

The app runs **fully offline** on synthetic data — no API keys needed to try it.

```bash
# 1. Backend
cd backend
python -m venv .venv
.venv\Scripts\activate              # Windows  (source .venv/bin/activate on macOS/Linux)
pip install -r requirements.txt
copy .env.example .env              # optional: add keys later for live data / Claude
alembic upgrade head               # create the database schema
python -m app.seed                 # bootstrap a market regime (synthetic if no keys)
python -m app.demo                 # optional: add sample strategies + proposals to explore
uvicorn app.main:app --reload      # http://localhost:8000/health

# 2. Frontend (separate terminal)
cd frontend
npm install
npm run dev                        # http://localhost:3000

# 3. Worker (optional, separate terminal) — runs the 5-minute trading loop
cd backend && .venv\Scripts\activate && python -m app.worker
```

### Docker (Postgres)
```bash
docker compose up --build          # backend :8000 · frontend :3000
```

### Configuration (`backend/.env`)
| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Empty = local SQLite (zero-config). Postgres: `postgresql+psycopg://trader:trader@localhost:5432/regime_trader` |
| `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` | Alpaca **paper** keys (free IEX data). Optional — synthetic data is used without them. |
| `ALPACA_PAPER` | Must stay `true`; the guard rejects `false`. |
| `ANTHROPIC_API_KEY` | Enables Claude-generated proposals. Optional. |
| `ALERT_WEBHOOK_URL` | Optional. POST critical alerts to a Slack/Discord-style webhook. |

Secrets live only in the gitignored backend `.env` and are **never** sent to the frontend or the LLM. `GET /settings` returns only booleans (`alpaca_configured`, `anthropic_configured`), never the keys.

---

## Using the app
1. **Dashboard** — see the current market regime, strategy count, and risk status.
2. **Strategies → New strategy** — pick *Manual* or *Self-learning*, set a ticker universe.
3. **Manual:** open a strategy → edit its `regime_rules` in the spec editor → **Save** → applies instantly and versions.
4. **Self-learning:** improvements appear in **Approvals** with a rationale + backtest → **Approve / Reject**.
5. **Promote** the best performer to trade the live paper account; the rest keep running in simulation.

---

## Q3 · Use cases & impact

- **Everyday investors** who want a calm, rule-based system instead of emotional trading.
- **People learning quantitative finance** — because it's paper-only, it's a completely safe sandbox to experiment with real strategies and lose nothing.
- **Anyone who distrusts black-box bots** — every decision is transparent: the market mood, the exact rules, the AI's reasoning, and a full version history are all visible.

The broader value is **democratizing disciplined investing**: it puts a regime-aware, risk-managed system — the kind that used to require a hedge fund — into one person's hands, with guardrails so they can learn without hurting themselves.

---

## Evaluation & evidence

Correctness is enforced by an automated test suite (run `pytest` in `backend/`, `npm test` in `frontend/`):

- **No look-ahead bias** — tests prove regime inference at time *t* uses only data ≤ *t* (forward-filter output on a prefix equals the full-series output), features are causal, and walk-forward backtesting has no in-sample/out-of-sample leakage.
- **Risk layer** — each circuit breaker fires on simulated equity curves, including exact-threshold boundary cases (e.g. −10.000% drawdown), and the clamp tightens a too-loose strategy.
- **Safety guards** — a non-paper broker config raises; an API test asserts no secret ever appears in `/settings` output.
- **Determinism** — the simulator produces deterministic next-bar fills; metrics (return, drawdown, Sharpe, win-rate) are checked against hand-computed values, including degenerate inputs.
- **Backtests** report metrics against **benchmarks** (buy-and-hold, 200-day SMA, random) plus crash stress tests.
- **End-to-end** — an in-process test runs the whole vision (regime → strategy → simulated trade → proposal → approval) with no network or keys.

**Result:** 78 backend tests + 7 frontend tests passing; `ruff` and `next build` clean.

---

## Q4 · What I'd add next

- A **visual strategy builder** (sliders/forms) so rules are edited without touching JSON.
- **Charts** — backtest equity curves and a live price-with-regime overlay.
- A carefully-guarded path to **real-money trading** with extra confirmations and reconciliation.
- **More data & assets** — paid SIP data, options, crypto, and richer regime features.
- **Multi-user accounts** with real authentication (the schema already carries `user_id`).
- An on-demand **"suggest improvements"** button to trigger Claude proposals from the UI.

---

## Guardrails (non-negotiable, enforced in code + tests)
1. **Paper-only lock** — no real-money path ships; non-paper config raises.
2. **No look-ahead** — forward-filtering only; causal features.
3. **Risk layer is supreme** — hardcoded breakers + clamp, independent of the AI.
4. **Nothing auto-mutates a live strategy** — user edits apply directly; every AI proposal requires explicit approval and creates a new immutable version.
5. **Secrets stay in the backend** — never exposed to the frontend or the LLM.

---

## Process, integrity & AI-usage disclosure

This is a **solo project**, built from scratch (the repository began empty — no forked or borrowed base code). All product, architecture, and risk-design decisions are my own.

Per the course AI policy, here is **how and where AI tools were used**: I built this project using **Claude Code** (Anthropic's agentic coding tool, Claude Opus) as a pair-programmer to scaffold and implement the FastAPI backend, the HMM regime engine, the risk layer, the Next.js frontend, and the test suite under my direction. I specified the requirements, made the design and safety decisions, and reviewed the code and tests. The application also uses the **Anthropic Claude API** at runtime as the optional self-learning proposer (see [`backend/app/engine/learning/`](backend/app/engine/learning/)). Development history is visible in the public commit log.

### Limitations (honest disclosure)
- **Paper-only** — not validated with real capital; live trading is deliberately out of scope for v1.
- The default market-data feed is Alpaca's free **IEX** feed (a subset of US volume); full **SIP** coverage is a paid upgrade.
- The self-learning proposer operates on a structured spec DSL; arbitrary sandboxed strategy code is a future stretch.
- Offline demos use **synthetic** data; live behavior requires Alpaca/Anthropic keys and market hours.

---

*Author: Ian Song · Stanford CS 153. Educational project — not financial advice.*
