# RunwayKeeper

> Autonomous Cash-Flow Operations Agent for Small Agencies & Service Businesses.
> Built for the **Agents for Humans** hackathon (Professional Agents Track).

RunwayKeeper answers three daily cash-flow questions for busy operators:
1. **Could our cash fall below our required buffer?**
2. **Which outstanding invoices contribute to that risk?**
3. **What follow-up can be completed right now within verified policy?**

---

## Key Architectural Principles

- **Deterministic Numerical Core**: LLMs never invent or alter cash balances, percentiles, or sensitivity values. A deterministic Monte Carlo simulation (2,000 seeded scenarios) with empirical Kaplan–Meier payment survival estimation models future arrivals.
- **Strands Agent Tool Orchestration**: Follow-ups, reconciliation searches, dispute routing, and forecasts execute via custom Strands tools (`@tool`).
- **Immutable Ledger Invariants**: All monetary amounts are integer minor units (cents). Currency mismatches, over-allocations, and closing unpaid invoices without settled allocations are rejected.
- **Exceptions-First Owner UX**: Routine follow-ups operate autonomously under strict cooldown and contact permission guards. Only items requiring judgment (disputed balances, ambiguous payments, altered terms) generate owner decision cards.
- **Resettable Simulation**: Ships with a pre-configured fictional agency ("Harbour Studio") and captures outbound emails with clear test labels to enable safe end-to-end evaluation.

---

## Monorepo Layout

```
runwaykeeper/
├── apps/
│   ├── api/                 # FastAPI REST API, background worker & migrations
│   │   ├── app/             # Application routers, models, ledger, services
│   │   ├── worker.py        # Durable polling job worker
│   │   └── data/fixtures/   # CSV fixture data for imports
│   └── web/                 # Next.js 14 minimal exceptions-first dashboard
├── packages/
│   ├── agent/               # Strands Agent tools, coordinator & schemas
│   └── forecasting/         # Deterministic numerical forecasting engine
├── tests/                   # Pytest test suite (forecasting, ledger, agent, imports)
└── docker-compose.yml       # Local development stack with PostgreSQL
```

---

## Getting Started

### Prerequisites

- Python 3.12+
- Node.js 20+ & pnpm
- (Optional) PostgreSQL & Docker

### 1. Install Dependencies

```bash
# Python packages
python3 -m venv .venv
source .venv/bin/activate
pip install -r apps/api/requirements.txt
pip install -e packages/forecasting -e packages/agent

# Frontend packages
cd apps/web && pnpm install && cd ../..
```

### 2. Run Tests

```bash
.venv/bin/pytest -v
```

All 24 unit and integration tests will run with an isolated in-memory/test database.

### 3. Run Locally

#### Option A: Docker Compose
```bash
docker compose up --build
```
- Web UI: http://localhost:3000
- API Docs: http://localhost:8000/docs

#### Option B: Bare Metal Development

In terminal 1 (API):
```bash
DATABASE_URL=sqlite:///runwaykeeper.db uvicorn app.main:app --host 0.0.0.0 --port 8000 --app-dir apps/api
```

In terminal 2 (Worker):
```bash
DATABASE_URL=sqlite:///runwaykeeper.db python apps/api/worker.py
```

In terminal 3 (Web UI):
```bash
cd apps/web && pnpm dev
```

---

## Strands Agent Tools

RunwayKeeper registers custom Strands tools (`packages/agent/runwaykeeper_agent/tools.py`):
- `load_case`: Loads customer, invoice, and permissions evidence.
- `calculate_forecast`: Triggers numerical simulation and persists percentile bands.
- `rank_followups`: Computes cash-gap sensitivity and ranks eligible cases.
- `search_payments`: Checks ledger payments when customer asserts "already paid".
- `propose_allocation`: Creates an owner approval card for non-trivial payment matches.
- `record_promise`: Records expected arrival date for what-if counterfactual scenario only (never settles actual balance).
- `open_dispute`: Transitions case to disputed and requests owner decision.
- `draft_reminder`: Drafts professional, context-aware invoice reminder.
- `enqueue_authorized_message`: Enqueues message only if recipient email is verified and opted in.
- `request_owner_decision`: Surfaces exceptions directly to the owner.

---

## Inbound Email Webhook & Simulation

In simulation mode, send test inbound emails directly via the API or dashboard:
```bash
curl -X POST http://localhost:8000/api/simulation/inbound \
  -H "X-API-Key: rk_demo_harbor_studio" \
  -H "Content-Type: application/json" \
  -d '{
    "from_email": "ap@northwind.test",
    "subject": "Already paid",
    "body": "This invoice was already paid. Reference INV-1042.",
    "invoice_reference": "INV-1042"
  }'
```

In connected mode, configure the Resend webhook endpoint pointing to `/api/events/resend` with Svix signature verification.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
