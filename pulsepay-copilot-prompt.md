

## How to use this document

GitHub Copilot Chat works best with **scoped, sequential prompts** — one domain at a time, with explicit file targets. Unlike long-context tools, Copilot Chat operates on what's open in your editor plus what you paste into chat.

**Workflow for each phase:**

1. Open the relevant file(s) in VS Code / JetBrains before pasting the prompt
2. Paste the prompt exactly as written
3. Review output, apply it, then move to the next phase
4. Never skip phases — later prompts depend on earlier ones being in place

---

## Pre-flight: Project Bootstrap

Before any domain work, run this once to scaffold the shell.

```
Create a FastAPI project called pulsepay with the following package structure. Do not write any implementation — only create the directory tree and empty __init__.py files. Use this exact layout:

pulsepay/
├── core/
│   ├── __init__.py
│   ├── config.py
│   ├── database.py
│   ├── exceptions.py
│   ├── middleware.py
│   └── dependencies.py
├── payments/
│   ├── __init__.py
│   ├── models.py
│   ├── schemas.py
│   ├── service.py
│   ├── router.py
│   └── state_machine.py
├── webhooks/
│   ├── __init__.py
│   ├── models.py
│   ├── schemas.py
│   ├── service.py
│   ├── dispatcher.py
│   └── router.py
├── ledger/
│   ├── __init__.py
│   ├── models.py
│   ├── schemas.py
│   └── service.py
├── refunds/
│   ├── __init__.py
│   ├── models.py
│   ├── schemas.py
│   ├── service.py
│   └── router.py
├── jobs/
│   ├── __init__.py
│   ├── queue.py
│   ├── worker.py
│   ├── models.py
│   └── handlers.py
├── ratelimit/
│   ├── __init__.py
│   ├── middleware.py
│   └── store.py
├── observability/
│   ├── __init__.py
│   ├── logging.py
│   ├── metrics.py
│   └── tracing.py
├── main.py
├── alembic.ini
├── requirements.txt
└── .env.example

Also create an alembic/ directory with versions/ inside it.
```

---

## Phase 1 — Core Infrastructure

**Files to open:** `core/config.py`, `core/database.py`, `core/exceptions.py`

```
I am building PulsePay, a FastAPI payments backend. Write the core infrastructure layer across three files.

Rules that apply to everything you write:
- No tutorial comments. Comments only where the why is non-obvious.
- All config via environment variables. No hardcoded values.
- Full type annotations throughout. No use of Any.
- Async SQLAlchemy with asyncpg driver for PostgreSQL.

core/config.py:
Use pydantic-settings BaseSettings. Include these fields with sensible defaults where appropriate: DATABASE_URL, SECRET_KEY, ENVIRONMENT (literal: development | staging | production), API_RATE_LIMIT_PER_MINUTE (int, default 100), API_BURST_LIMIT_PER_SECOND (int, default 20), WEBHOOK_SIGNING_SECRET, MAX_PAYMENT_RETRY_ATTEMPTS (int, default 3), SEED_ON_STARTUP (bool, default False). Expose a cached settings() function using lru_cache.

core/database.py:
Async SQLAlchemy engine and session factory using asyncpg. Declarative Base with these mixins on all models: UUID primary key (server-side default via gen_random_uuid()), created_at and updated_at with server-side defaults. Expose get_db as an async generator for FastAPI Depends injection. Do not use NullPool — use a proper async pool with reasonable defaults.

core/exceptions.py:
Define a base PulsePayException with a string error_code field and an HTTP status. Then define these concrete exceptions with appropriate status codes: PaymentNotFound, PaymentAlreadyProcessed, InvalidStateTransition, IdempotencyConflict, InsufficientRefundableAmount, RefundExceedsOriginal, WebhookDeliveryFailed, RateLimitExceeded, JobQueueFull. Each exception must carry a detail message. Add an error_code string constant for each (e.g. PAYMENT_NOT_FOUND). Include a FastAPI exception handler registration function that formats all errors as: {"error": {"code": "...", "message": "...", "request_id": "..."}}.
```

---

## Phase 2 — Observability

**Files to open:** `observability/logging.py`, `observability/tracing.py`, `core/middleware.py`

```
Write the observability layer for PulsePay.

observability/logging.py:
Configure Python's logging module with a JSON formatter. Every log record must include: timestamp (ISO 8601), level, service (always "pulsepay"), request_id (pulled from contextvars), and the message. Expose a get_logger(name) factory. No print() statements anywhere in the codebase — this logger replaces them all.

observability/tracing.py:
Use Python's contextvars module to store and retrieve request_id (UUID) for the lifetime of a single request. Expose: set_request_id(id: str), get_request_id() -> str | None, and a context manager new_request_context() that generates and sets a fresh UUID.

core/middleware.py:
Write two Starlette middleware classes.

RequestTracingMiddleware: Runs on every request. Generates a request_id UUID, sets it via the tracing module, injects it into response headers as X-Request-ID, and wraps the request in the tracing context.

LoggingMiddleware: Logs every request/response as structured JSON at INFO level. Log fields: method, path, status_code, duration_ms, request_id. Do not log request bodies.

These two middleware classes are the only place these cross-cutting concerns are handled. Do not replicate this logic in route handlers.
```

---

## Phase 3 — Payments Domain

**Files to open:** `payments/models.py`, `payments/schemas.py`, `payments/state_machine.py`, `payments/service.py`, `payments/router.py`

```
Write the complete payments domain for PulsePay.

payments/models.py:
Define Payment and IdempotencyRecord SQLAlchemy models.

Payment fields: id (UUID PK), customer_id (str, indexed), amount (Numeric 12,2), currency (str, 3 chars), status (str, indexed — values: pending, processing, success, failed), failure_reason (str, nullable), failure_class (str, nullable — values: soft, hard), retry_count (int, default 0), idempotency_key (str, unique), metadata (JSON, nullable), state_history (JSON, default empty list — append-only log of {state, timestamp, reason} dicts), confirmed_at (DateTime, nullable), created_at, updated_at.

IdempotencyRecord fields: id (UUID PK), key (str, unique, indexed), response_body (JSON), status_code (int), expires_at (DateTime), created_at.

Unique constraint on (customer_id, idempotency_key) at the DB level.

payments/state_machine.py:
Implement a PaymentStateMachine class. Valid transitions: pending → processing, processing → success, processing → failed. Any other transition raises InvalidStateTransition. The transition method takes the current payment and target state, validates the transition, appends to state_history, and returns the updated payment — it does not commit to DB, the service layer does that.

payments/schemas.py:
Pydantic v2 schemas. CreatePaymentRequest: customer_id, amount (Decimal, > 0), currency (3-char uppercase), metadata (dict | None). PaymentResponse: full payment representation including state_history. ConfirmPaymentRequest: optional metadata. PaginatedPaymentsResponse wrapping list[PaymentResponse] with page/limit/total.

payments/service.py:
PaymentService class injected with AsyncSession.

create_payment: Accepts CreatePaymentRequest and idempotency_key. Check idempotency_key — if seen within 24h, return the stored response. Otherwise create a Payment in pending state, write IdempotencyRecord, enqueue a background job (job type: process_payment) and return the payment. Do not process inline.

confirm_payment: Called from the background job worker, not from an HTTP handler. Transition to processing, then simulate a downstream processor call: 85% success, 10% soft failure (retriable), 5% hard failure (terminal). On soft failure raise a soft-classified exception. On hard failure mark as failed with reason. On success transition to success, write a ledger entry, emit a webhook event.

get_payment: Fetch by id, raise PaymentNotFound if missing.

list_payments: Paginated query with optional customer_id and status filters. Max limit 100.

payments/router.py:
Four routes under /v1/payments:
- POST / — create payment intent, requires Idempotency-Key header
- POST /{payment_id}/confirm — confirm payment (this will also be called by the job worker, but expose it as an HTTP endpoint too)
- GET /{payment_id} — get payment
- GET / — list payments with customer_id, status, page, limit query params

All responses use the envelope: {"data": {...}, "meta": {"request_id": "...", "timestamp": "..."}}. HTTP semantics must be correct. 409 for idempotency conflicts, 422 for validation, 404 for not found.
```

---

## Phase 4 — Retry & Failure Handling

**Files to open:** `payments/service.py`, `jobs/handlers.py`

```
Add retry and failure handling to PulsePay's payment processing.

Open payments/service.py. The confirm_payment method already has a simulated processor. Now add retry logic around the soft failure path:

- Soft failures are retriable. Hard failures are not.
- Retry uses exponential backoff with jitter: base_delay = 2 ** retry_count seconds, jitter = random float 0–1 added to base. Do not sleep inline — enqueue a delayed retry job.
- Max retries is read from settings (MAX_PAYMENT_RETRY_ATTEMPTS, default 3).
- After exhausting retries, transition to failed with failure_class = "hard" and reason = "max_retries_exceeded".
- Increment retry_count on the Payment model each attempt.

Open jobs/handlers.py. Register two job handlers:
- process_payment: calls payment_service.confirm_payment. On soft failure, re-enqueues the job with retry metadata including attempt number and next_run_at calculated from the backoff formula.
- retry_payment: same as process_payment but checks retry_count against max before proceeding. If max exceeded, marks payment failed and emits payment.failed webhook event.

Both handlers must log structured JSON at each decision point: attempt number, failure class, next retry delay. No print statements.
```

---

## Phase 5 — Ledger

**Files to open:** `ledger/models.py`, `ledger/schemas.py`, `ledger/service.py`

```
Write the ledger domain for PulsePay.

ledger/models.py:
LedgerEntry model. Fields: id (UUID PK), payment_id (UUID, FK to payments.id, indexed), customer_id (str, indexed), event_type (str — values: payment.created, payment.processing, payment.success, payment.failed, refund.initiated, refund.completed), amount (Numeric 12,2), currency (str), running_balance (Numeric 12,2, nullable), metadata (JSON, nullable), created_at.

This is an append-only ledger. Do not expose any update or delete operations on this model anywhere — not in the service, not in the router. Add a class-level docstring stating this invariant.

ledger/service.py:
LedgerService injected with AsyncSession.

record_entry: Inserts a LedgerEntry. This is called by the payment and refund services, never directly from routers. Accepts payment_id, customer_id, event_type, amount, currency, metadata.

get_customer_ledger: Returns all entries for a customer_id ordered by created_at descending, paginated.

ledger/schemas.py:
LedgerEntryResponse schema. PaginatedLedgerResponse wrapping list[LedgerEntryResponse] with page/limit/total.

Add a GET /v1/ledger/{customer_id} route in a new ledger/router.py file. Paginated. Read-only — no write endpoints.
```

---

## Phase 6 — Webhooks

**Files to open:** `webhooks/models.py`, `webhooks/schemas.py`, `webhooks/service.py`, `webhooks/dispatcher.py`, `webhooks/router.py`

```
Write the webhook delivery system for PulsePay.

webhooks/models.py:
Two models.

WebhookEndpoint: id (UUID PK), client_id (str, indexed), url (str), signing_secret (str), is_active (bool, default True), created_at, updated_at.

WebhookEvent: id (UUID PK), endpoint_id (UUID FK), event_type (str), payload (JSON), status (str — queued, delivered, failed, dead), attempt_count (int, default 0), last_attempt_at (DateTime, nullable), next_retry_at (DateTime, nullable), created_at, updated_at.

webhooks/dispatcher.py:
WebhookDispatcher class.

dispatch(event_type, payload, customer_id): Looks up active WebhookEndpoints for the client, creates a WebhookEvent per endpoint, enqueues a deliver_webhook job for each.

deliver(event_id): Fetches the WebhookEvent. Builds the signed HTTP request — HMAC-SHA256 of the JSON payload body using the endpoint's signing_secret. Include the signature as X-PulsePay-Signature header and the event timestamp as X-PulsePay-Timestamp. Simulate the HTTP POST (do not require a live URL — use httpx with a short timeout; if connection refused or timeout, treat as delivery failure). On failure, increment attempt_count and schedule retry with exponential backoff. Max 5 attempts. After 5, mark as dead.

webhooks/service.py:
WebhookService: list_events with status filter and pagination. get_event by id. register_endpoint. deactivate_endpoint.

webhooks/router.py:
- GET /v1/webhooks/events — list events, filterable by status
- GET /v1/webhooks/events/{event_id} — get single event
- POST /v1/webhooks/endpoints — register endpoint
- DELETE /v1/webhooks/endpoints/{endpoint_id} — deactivate

All responses use the standard envelope.
```

---

## Phase 7 — Refunds

**Files to open:** `refunds/models.py`, `refunds/schemas.py`, `refunds/service.py`, `refunds/router.py`

```
Write the refund domain for PulsePay.

refunds/models.py:
Refund model. Fields: id (UUID PK), payment_id (UUID FK, indexed), customer_id (str, indexed), amount (Numeric 12,2), currency (str), status (str — pending, processing, completed, failed), reason (str, nullable), idempotency_key (str, unique), created_at, updated_at.

refunds/service.py:
RefundService injected with AsyncSession.

initiate_refund: Accepts payment_id, amount (optional — if None, full refund), idempotency_key, reason.
- Fetch the payment. Raise PaymentNotFound if missing.
- Payment must be in success state. Raise InvalidStateTransition otherwise.
- Sum all non-failed refunds for this payment. If requested amount + existing refunds > original amount, raise InsufficientRefundableAmount with a message that includes the refundable amount remaining.
- Create Refund in pending state.
- Write a ledger entry for refund.initiated.
- Enqueue process_refund job.
- Return refund.

process_refund: Called from job worker. Simulate refund processor (95% success). On success: transition to completed, write ledger entry for refund.completed, emit refund.completed webhook. On failure: transition to failed.

list_refunds: All refunds for a payment_id.

refunds/router.py:
- POST /v1/payments/{payment_id}/refunds — initiate refund, requires Idempotency-Key header
- GET /v1/payments/{payment_id}/refunds — list refunds

Enforce: partial refund amount must be > 0. Full refund if amount not provided.
```

---

## Phase 8 — Rate Limiting

**Files to open:** `ratelimit/store.py`, `ratelimit/middleware.py`

```
Write the rate limiting layer for PulsePay.

ratelimit/store.py:
Implement a token bucket rate limiter in-process.

TokenBucket dataclass: tokens (float), last_refill (float timestamp), capacity (float), refill_rate (float tokens/sec).

RateLimitStore: module-level dict mapping client API key → TokenBucket. consume(api_key, tokens=1) -> tuple[bool, float]: returns (allowed, retry_after_seconds). If the key is new, initialize a bucket from settings. Bucket capacity = API_RATE_LIMIT_PER_MINUTE / 60 * capacity_seconds — tune this so burst and sustained limits both work.

Add a single comment here (this is one of two permitted explanatory comments in the codebase): note that this store is module-level state and is not safe for multi-process deployments; in production this would be backed by Redis with a Lua script for atomic token consumption.

ratelimit/middleware.py:
RateLimitMiddleware Starlette middleware. Reads X-API-Key header. If missing, return 401 with {"error": {"code": "MISSING_API_KEY", "message": "...", "request_id": "..."}}. Call store.consume(). If not allowed, return 429 with Retry-After header set to the retry_after_seconds value. Skip rate limiting for /health and /v1/metrics routes.
```

---

## Phase 9 — Background Job System (StormQueue)

**Files to open:** `jobs/models.py`, `jobs/queue.py`, `jobs/worker.py`, `jobs/handlers.py`

```
Write StormQueue — PulsePay's in-process async background job system. This is a first-class component, not a utility.

jobs/models.py:
Job SQLAlchemy model. Fields: id (UUID PK), job_type (str, indexed), payload (JSON), status (str, indexed — queued, running, completed, failed, dead), attempt_count (int, default 0), max_attempts (int, default 3), run_at (DateTime, server default now(), indexed — used for delayed jobs), last_error (str, nullable), created_at, updated_at.

jobs/queue.py:
StormQueue class.

Internal state: asyncio.Queue for in-memory dispatch, AsyncSession factory for persistence.

enqueue(job_type, payload, run_at=None, max_attempts=3): Persists Job to DB with status=queued, then puts job_id into the asyncio.Queue. If run_at is in the future, do not put into the queue immediately — the worker polls for due delayed jobs.

get_dead_jobs(page, limit): Returns paginated dead jobs from DB.

retry_dead_job(job_id): Resets status to queued, clears last_error, re-enqueues.

jobs/worker.py:
JobWorker class.

start(): Starts two asyncio tasks — one consuming from the queue, one polling DB every 5s for delayed jobs whose run_at <= now() and re-enqueueing them.

_process(job_id): Fetches job, marks running, calls the registered handler. On success marks completed. On exception: increments attempt_count, logs the error with job_id and attempt. If attempt_count < max_attempts re-enqueues. Otherwise marks dead and logs at ERROR level.

The worker is started in main.py on app startup via lifespan. It shuts down cleanly on app shutdown.

jobs/handlers.py:
Handler registry: dict mapping job_type string → async callable.

Register these handlers (implementations call into the relevant service):
- process_payment
- retry_payment
- deliver_webhook
- process_refund

Expose register_handler(job_type, fn) and get_handler(job_type) -> callable | None. Raise a clear exception if an unregistered job_type is dispatched.
```

---

## Phase 10 — Metrics Endpoint & main.py

**Files to open:** `observability/metrics.py`, `main.py`

```
Write the metrics endpoint and wire everything together in main.py.

observability/metrics.py:
MetricsService injected with AsyncSession. Computes and returns:
- total_payments (int)
- successful_payments (int)
- failed_payments (int)
- success_rate_pct (float, 0–100)
- failure_rate_pct (float, 0–100)
- avg_processing_time_ms (float — time between created_at and confirmed_at on successful payments)
- active_jobs (int — queued + running)
- dead_jobs (int)

Add GET /v1/metrics route. No auth required. Response is not enveloped — return the metrics dict directly. This endpoint is also excluded from rate limiting.

main.py:
Wire the full application.

Use FastAPI lifespan context manager (not deprecated on_event). In startup: run Alembic migrations programmatically if ENVIRONMENT == "development", start the JobWorker, seed data if SEED_ON_STARTUP is true. In shutdown: stop the JobWorker gracefully.

Register all routers with /v1 prefix.
Register exception handlers from core/exceptions.py.
Register RequestTracingMiddleware and LoggingMiddleware and RateLimitMiddleware — in that order (tracing first, so request_id is available to logging).

Add GET /health endpoint returning {"status": "ok", "environment": settings.ENVIRONMENT}. No auth, no rate limit.

Include app metadata: title="PulsePay", version="1.0.0", docs_url="/docs" only in development.
```

---

## Phase 11 — Database Migration & Seed Data

**Files to open:** `alembic/env.py`, create `seed.py`

```
Write the Alembic migration and seed data for PulsePay.

alembic/env.py:
Configure for async SQLAlchemy with asyncpg. Import all models so Alembic can detect them. Use the DATABASE_URL from settings. Target metadata is the shared Base.metadata.

Generate the initial migration as alembic/versions/0001_initial_schema.py. It must create all tables: payments, idempotency_records, ledger_entries, refunds, webhook_endpoints, webhook_events, jobs. Include all indexes and the unique constraint on (customer_id, idempotency_key) on payments. Write both upgrade() and downgrade().

seed.py (runs only when SEED_ON_STARTUP=true in development):
Create:
- 3 API clients, each with a generated API key (store in a module-level dict that the rate limiter can reference)
- 2 webhook endpoints per client pointing to https://webhook.site/test-{client_id} (no live delivery required)
- 10 payments in mixed states: 4 success, 2 failed, 2 pending, 2 processing
- Corresponding ledger entries for the success and failed payments
- 2 refunds against the successful payments

Seed is idempotent — running it twice does not create duplicate records (use ON CONFLICT DO NOTHING or check-before-insert).
```

---

## Phase 12 — Tests

**Files to open:** Create `tests/` directory

```
Write targeted tests for PulsePay's critical paths. Do not test everything — test what breaks the system if wrong.

Create:

tests/conftest.py:
Async pytest fixtures using anyio. In-memory SQLite for tests (override DATABASE_URL). Fixtures: db_session, test_client (httpx AsyncClient against the FastAPI app), sample_payment, sample_customer_id.

tests/test_payments.py:
- test_create_payment_success: POST /v1/payments returns 201 with pending payment
- test_idempotency_returns_same_response: Same Idempotency-Key twice returns identical response without creating duplicate
- test_invalid_state_transition: Attempting to confirm an already-completed payment returns 409
- test_payment_not_found: GET /v1/payments/nonexistent-id returns 404 with correct error code

tests/test_refunds.py:
- test_partial_refund_success
- test_refund_exceeds_original_raises_409
- test_refund_on_non_success_payment_raises_409

tests/test_state_machine.py:
- test_valid_transitions: All valid transitions succeed
- test_invalid_transition_raises: pending → success raises InvalidStateTransition
- test_state_history_appended: Each transition appends a record to state_history

tests/test_rate_limit.py:
- test_missing_api_key_returns_401
- test_rate_limit_exceeded_returns_429_with_retry_after

Use pytest-anyio. All test functions are async. No mocking of the DB — use the real async session with SQLite. Mock the external webhook HTTP call in refund/webhook tests.
```

---

## Phase 13 — Final Files

**Create:** `requirements.txt`, `.env.example`, `README.md`

```
Create the three final files for PulsePay.

requirements.txt:
Pin all dependencies. Include: fastapi, uvicorn[standard], sqlalchemy[asyncio], asyncpg, alembic, pydantic-settings, pydantic[email], httpx, python-multipart, pytest, pytest-anyio, anyio, aiosqlite (for tests). Pin to specific versions that are mutually compatible as of mid-2025.

.env.example:
All environment variables with placeholder values and a one-line comment above each explaining what it controls. Group by: Database, Security, Application, Rate Limiting, Jobs, Observability.

README.md:
Sections:
1. Local Setup — prerequisites, clone, env setup, run migrations, start server
2. Environment Variables — table with name, description, default
3. Architecture Decisions — four subsections:
   a. Folder structure rationale (domain-driven, not framework-driven)
   b. Payment state machine design (why explicit transitions, what the state_history log enables)
   c. StormQueue design (why in-process, trade-offs vs Celery/Redis, what would change in production)
   d. Rate limiting trade-off (token bucket, in-process limitation, production path)
4. API Overview — table of all endpoints with method, path, auth required, description
5. Running Tests

Write the README as if it will be read by a new engineer joining the team. It should be informative without being verbose.
```

---

## Copilot Chat Tips for This Project

These notes will save you time when working through the phases above.

**Keep context focused.** Before pasting each phase prompt, close unrelated files. Copilot Chat uses open editor tabs as context — too many open files degrades output quality.

**Use `#file:` references.** In VS Code Copilot Chat, you can reference a specific file by typing `#file:payments/service.py` in the prompt. For phases that touch multiple files, reference each one explicitly.

**If output is truncated.** Copilot Chat may stop mid-file on long outputs. Type `continue` and it will resume from where it stopped.

**If output diverges from the spec.** Paste the specific rule it violated back as a follow-up: *"The service layer is calling the DB directly in the router — move all DB access into the service."* Be specific about what went wrong rather than asking it to redo everything.

**Run tests after Phase 12 before Phase 13.** Tests will surface integration issues between domains before you write final documentation.

**Do not run all phases in one session.** Each phase builds on the previous. Apply and review output before moving forward.

---

*PulsePay Backend Prompt Guide — GitHub Copilot Chat Edition*  
*For use with: VS Code or JetBrains + GitHub Copilot Chat*
