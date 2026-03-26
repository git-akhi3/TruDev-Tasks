# PulsePay

PulsePay is a FastAPI backend for payment processing, refunds, webhooks, rate limiting, and asynchronous background jobs.

## 1. Local Setup

### Prerequisites

- Python 3.11+
- PostgreSQL 14+
- pip

### Clone and install

1. Clone the repository.
2. Change into the pulsepay directory.
3. Create and activate a virtual environment.
4. Install dependencies:

```bash
pip install -r requirements.txt
```

### Environment setup

1. Copy .env.example to .env.
2. Update values for your local machine, especially DATABASE_URL, SECRET_KEY, and WEBHOOK_SIGNING_SECRET.

### Run migrations

From the pulsepay directory:

```bash
alembic -c alembic.ini upgrade head
```

### Start the server

```bash
uvicorn main:app --reload
```

Server will be available at http://127.0.0.1:8000.

## 2. Environment Variables

| Name | Description | Default |
|---|---|---|
| DATABASE_URL | Async database connection string used by API and worker | Required |
| DB_POOL_SIZE | Base SQLAlchemy connection pool size | 10 |
| DB_MAX_OVERFLOW | Additional overflow connections allowed | 20 |
| DB_POOL_TIMEOUT_SECONDS | Seconds to wait when pool is exhausted | 30 |
| DB_POOL_RECYCLE_SECONDS | Seconds before recycling pooled connections | 1800 |
| SECRET_KEY | Application secret for security-sensitive operations | Required |
| WEBHOOK_SIGNING_SECRET | Secret used to sign webhook payloads | Required |
| ENVIRONMENT | Runtime environment, affects docs and startup behavior | development |
| SEED_ON_STARTUP | Enables development seed routine at app startup | false |
| API_RATE_LIMIT_PER_MINUTE | Sustained per-key request budget | 100 |
| API_BURST_LIMIT_PER_SECOND | Short burst per-key request budget | 20 |
| MAX_PAYMENT_RETRY_ATTEMPTS | Retry cap for payment processing flows | 3 |

## 3. Architecture Decisions

### a. Folder structure rationale

The codebase is domain-driven rather than framework-driven. Each domain package (payments, refunds, webhooks, jobs, ratelimit, observability) owns its models, schemas, routers, and service logic. This keeps features cohesive, shortens navigation time, and reduces cross-module coupling as the system grows.

### b. Payment state machine design

Payment lifecycle transitions are explicit and validated through a state machine. This prevents illegal transitions from creeping into handlers and routers. The state_history trail captures every transition reason and timestamp, which improves auditability, debugging, and incident reconstruction.

### c. StormQueue design

StormQueue is an in-process async job system backed by durable DB job records. This keeps operational complexity low for early-stage deployment while still providing retries, delayed scheduling, and dead-letter visibility. Compared with Celery and Redis, this is simpler to run but less horizontally scalable. In production at higher throughput, the queue backend and dispatch mechanism can be moved to Redis or a managed queue while preserving the current handler contract.

### d. Rate limiting trade-off

Rate limiting uses a token bucket algorithm with in-memory buckets. It is fast and easy to reason about for single-process deployments, and supports both burst and sustained controls. The trade-off is process-local state, so limits are not globally consistent across multiple app instances. Production evolution path is Redis-backed atomic token consumption.

## 4. API Overview

| Method | Path | Auth Required | Description |
|---|---|---|---|
| GET | /health | No | Liveness check with environment |
| GET | /v1/metrics | No | Aggregate operational metrics |
| POST | /v1/payments/ | Yes (X-API-Key, Idempotency-Key) | Create a payment in pending state |
| POST | /v1/payments/{payment_id}/confirm | Yes (X-API-Key) | Confirm and process a payment |
| GET | /v1/payments/{payment_id} | Yes (X-API-Key) | Fetch a payment by id |
| GET | /v1/payments/ | Yes (X-API-Key) | List payments with pagination and optional filters |
| POST | /v1/payments/{payment_id}/refunds | Yes (X-API-Key, Idempotency-Key) | Initiate full or partial refund |
| GET | /v1/payments/{payment_id}/refunds | Yes (X-API-Key) | List refunds for a payment |
| GET | /v1/webhooks/events | Yes (X-API-Key) | List webhook delivery events |
| GET | /v1/webhooks/events/{event_id} | Yes (X-API-Key) | Get webhook event details |
| POST | /v1/webhooks/endpoints | Yes (X-API-Key) | Register webhook endpoint |
| DELETE | /v1/webhooks/endpoints/{endpoint_id} | Yes (X-API-Key) | Deactivate webhook endpoint |

## 5. Running Tests

Run the targeted critical-path suite:

```bash
python -m pytest -q tests/test_payments.py tests/test_refunds.py tests/test_state_machine.py tests/test_rate_limit.py
```

Run all tests:

```bash
python -m pytest -q
```
