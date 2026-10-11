# UTTT POC — Django REST Framework Learning Project

A repository containing two Django applications:

1. **Task API** — simple CRUD API, built first as a learning exercise.
2. **UTTT Platform** — test orchestration API that dispatches test cases to an external
   service, collects callbacks, and advances workflows through a state machine.
   A **mock external service** (separate Django project) on port 8001 is included so the
   full round-trip can be exercised without real infrastructure.

The platform runs on a Rocky Linux 9 VM.
Code is edited on Windows using VS Code and deployed to Linux via Git.

---

## Compatibility

| Component | Version | Notes |
|---|---|---|
| Python | 3.12 | Already installed on the Linux VM. |
| Django | 5.2 LTS | Active LTS, supported until April 2028. |
| Django REST Framework | 3.17.2+ | First DRF release patching CVE-2026-73228. |
| psycopg2-binary | 2.9.13 | PostgreSQL adapter. Binary wheel — no C build tools needed. |
| PostgreSQL | 15 | Django 5.2 requires PostgreSQL 14+. Upgraded from 13 using pg_upgrade + PGDG repo. |
| requests | 2.32+ | Used by the UTTT worker to call the external test service. |

---

## Project Structure

```
uttt-poc/
├── .env.example              # Template for UTTT env vars (copy to .env on Linux)
├── .gitignore
├── requirements.txt
├── manage.py                 # Django CLI for UTTT platform + Task API
│
├── taskapi/                  # Django project configuration
│   ├── settings.py           # Reads secrets from .env via python-decouple
│   ├── urls.py               # Routes /api/ to tasks + uttt apps; /admin/ to Django admin
│   └── wsgi.py
│
├── tasks/                    # Task CRUD app (learning exercise)
│   ├── models.py
│   ├── serializers.py
│   ├── views.py
│   ├── urls.py
│   ├── admin.py
│   └── tests.py
│
├── uttt/                     # UTTT platform app
│   ├── models.py             # Product, RegisteredTestCase, WorkflowRun, TestExecution,
│   │                         #   Dispatch, CallbackReceipt
│   ├── authentication.py     # X-Platform-Api-Key header authentication
│   ├── serializers.py        # Input/output serializers for all endpoints
│   ├── views.py              # ProductListCreate, TestCaseListCreate, WorkflowCreate, …
│   ├── urls.py               # URL routing for all platform endpoints
│   ├── worker.py             # State machine: dispatch → callback → advance workflow
│   ├── admin.py
│   ├── tests.py              # Full test suite (products, workflows, callbacks, timeouts, …)
│   └── management/commands/
│       ├── run_worker.py     # python manage.py run_worker
│       └── seed_uttt.py      # python manage.py seed_uttt  (creates Demo product + TC001–TC004)
│
└── mock_service/             # Separate Django project — simulates an external test service
    ├── manage.py             # python mock_service/manage.py <command>
    ├── .env.example          # Template for mock service env vars
    │
    ├── config/               # Mock service Django project configuration
    │   ├── settings.py       # SQLite database; reads mock_service/.env
    │   └── urls.py
    │
    └── runner/               # Mock service app
        ├── models.py         # MockTestDefinition, MockTestRun, MockExecution, PendingCallback
        ├── serializers.py
        ├── views.py          # POST /api/test-runs/, GET /api/test-runs/{id}/
        ├── urls.py
        ├── worker.py         # Transitions execution states, delivers callbacks to UTTT
        ├── admin.py
        └── management/commands/
            ├── run_mock_worker.py  # python mock_service/manage.py run_mock_worker
            └── seed_mock.py        # python mock_service/manage.py seed_mock
```

---

## UTTT Platform — How It Works

```
Windows (browser/curl)
  → POST /api/workflows/  (returns 202 + workflow_id)

UTTT worker (run_worker management command, loops every few seconds)
  → Picks up PENDING workflow
  → Creates a Dispatch, POSTs to mock_service:8001/api/test-runs/
  → Mock service accepts, schedules callbacks

Mock worker (run_mock_worker, loops)
  → After start_delay: POSTs RUNNING callback to UTTT /api/execution-events/
  → After complete_delay: POSTs PASSED/FAILED callback

UTTT callback endpoint (/api/execution-events/)
  → Validates X-Callback-Api-Key
  → Updates TestExecution status

UTTT worker (next cycle)
  → Sees all PRE tests terminal → advances workflow
  → PATCHING → creates POST dispatch → continues
  → All POST tests terminal → workflow PASSED or FAILED
```

### Test case behaviours (seeded by seed_mock)

| ID | Behaviour | Start delay | Complete delay |
|---|---|---|---|
| TC001 | Always passes | 0.5 s | 1.0 s |
| TC002 | Always passes (slow) | 0.5 s | TC002_DELAY_SECONDS (default 3 s) |
| TC003 | Always fails | 0.5 s | 1.0 s |
| TC004 | Never completes (timeout) | 0.5 s | — |

---

## Linux Setup

Run all commands in your Rocky Linux 9 terminal.

### Step 1 — Confirm Python 3.12

```bash
python3.12 --version   # should print Python 3.12.x
```

### Step 2 — Clone or pull the repository

```bash
# First time:
git clone https://github.com/YOUR_USER/uttt-poc.git
cd uttt-poc

# Subsequent pulls:
git pull
```

### Step 3 — Create the PostgreSQL database

```bash
psql -h 127.0.0.1 -U pg -c "CREATE DATABASE uttt;"
# If permission error:
sudo -u postgres psql -c "CREATE DATABASE uttt OWNER pg;"
```

### Step 4 — Create the Python virtual environment

```bash
python3.12 -m venv venv
source venv/bin/activate    # prompt changes to (venv)
```

> Activate the venv every time you open a new terminal.

### Step 5 — Install Python dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 6 — Create the .env file

```bash
cp .env.example .env
nano .env
chmod 600 .env
```

Minimum required values:

| Variable | How to set |
|---|---|
| `SECRET_KEY` | `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `DB_PASSWORD` | Password for your `pg` PostgreSQL user |
| `PLATFORM_API_KEY` | `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `PRODUCT_DEMO_API_KEY` | Any string, e.g. `demo-api-key-abc123` — must match `MOCK_API_KEY` in mock_service/.env |
| `PRODUCT_DEMO_CALLBACK_SECRET` | Any string, e.g. `demo-cb-secret-xyz` — must match `UTTT_CALLBACK_API_KEY` in mock_service/.env |

### Step 7 — Run UTTT migrations

```bash
python manage.py makemigrations uttt
python manage.py migrate
```

Expected output ends with:
```
  Applying uttt.0001_initial... OK
```

### Step 8 — Seed the UTTT platform

```bash
python manage.py seed_uttt
```

This creates the Demo product and registers TC001–TC004 as test cases.

### Step 9 — (Optional) Create an admin superuser

```bash
python manage.py createsuperuser
```

### Step 10 — Start the UTTT server

```bash
python manage.py runserver 0.0.0.0:8000
```

---

## Mock Service Setup

The mock service is a separate Django project with its own settings and SQLite database.
Run these commands **in a second terminal** (with the venv active).

### Step 1 — Create the mock service .env file

```bash
cp mock_service/.env.example mock_service/.env
nano mock_service/.env
chmod 600 mock_service/.env
```

Required values:

| Variable | Value |
|---|---|
| `MOCK_API_KEY` | Must match `PRODUCT_DEMO_API_KEY` in the main `.env` |
| `UTTT_CALLBACK_API_KEY` | Must match `PRODUCT_DEMO_CALLBACK_SECRET` in the main `.env` |

### Step 2 — Run mock service migrations

```bash
python mock_service/manage.py migrate
```

### Step 3 — Seed TC001–TC004 definitions

```bash
python mock_service/manage.py seed_mock
```

### Step 4 — Start the mock service

```bash
python mock_service/manage.py runserver 0.0.0.0:8001
```

### Step 5 — Start the mock worker (third terminal)

```bash
source venv/bin/activate
python mock_service/manage.py run_mock_worker
```

---

## Running the UTTT Worker

Open a fourth terminal with the venv active:

```bash
source venv/bin/activate
python manage.py run_worker
```

The worker loops every `WORKER_POLL_INTERVAL_SECONDS` (default 3 s), driving the
workflow state machine.

---

## VirtualBox NAT Port Forwarding

You need two forwarding rules — one for each service.

In VirtualBox: VM → **Settings** → **Network** → **Adapter 1** (NAT) → **Advanced** → **Port Forwarding**.

| Name | Protocol | Host IP | Host Port | Guest Port |
|---|---|---|---|---|
| django | TCP | 127.0.0.1 | 8000 | 8000 |
| mock | TCP | 127.0.0.1 | 8001 | 8001 |

Allow both ports through the Linux firewall:

```bash
sudo firewall-cmd --add-port=8000/tcp --add-port=8001/tcp
sudo firewall-cmd --add-port=8000/tcp --add-port=8001/tcp --permanent
```

> If you see `FirewallD is not running`, skip this step.

---

## UTTT API Endpoints

All UTTT endpoints require `X-Platform-Api-Key: <your PLATFORM_API_KEY>`.

Substitute `<KEY>` with the value of `PLATFORM_API_KEY` from your `.env`.

### Register a product

```bash
curl -X POST http://127.0.0.1:8000/api/products/ \
  -H "Content-Type: application/json" \
  -H "X-Platform-Api-Key: <KEY>" \
  -d '{
    "name": "Demo Product",
    "external_api_base_url": "http://127.0.0.1:8001",
    "credential_env_key": "PRODUCT_DEMO_API_KEY",
    "callback_secret_env_key": "PRODUCT_DEMO_CALLBACK_SECRET",
    "enabled": true
  }'
```

> If you ran `seed_uttt`, the Demo Product already exists — skip this.

### List products

```bash
curl http://127.0.0.1:8000/api/products/ \
  -H "X-Platform-Api-Key: <KEY>"
```

Copy the product UUID from the response for use below.

### Register a test case

```bash
curl -X POST http://127.0.0.1:8000/api/test-cases/ \
  -H "Content-Type: application/json" \
  -H "X-Platform-Api-Key: <KEY>" \
  -d '{
    "product": "<PRODUCT_UUID>",
    "external_test_case_id": "TC001",
    "name": "Fast passing test",
    "enabled": true
  }'
```

> If you ran `seed_uttt`, TC001–TC004 are already registered — copy their UUIDs from
> `GET /api/test-cases/?product_id=<PRODUCT_UUID>`.

### List test cases

```bash
curl "http://127.0.0.1:8000/api/test-cases/?product_id=<PRODUCT_UUID>" \
  -H "X-Platform-Api-Key: <KEY>"
```

---

## UTTT Workflow Scenarios

### Scenario 1 — Happy path (PRE passes, patch, POST passes)

```bash
curl -X POST http://127.0.0.1:8000/api/workflows/ \
  -H "Content-Type: application/json" \
  -H "X-Platform-Api-Key: <KEY>" \
  -d '{
    "product_id": "<PRODUCT_UUID>",
    "pre_test_case_ids": ["<TC001_UUID>"],
    "post_test_case_ids": ["<TC002_UUID>"]
  }'
```

Response `202`:
```json
{"workflow_id": "...", "status": "PENDING", "status_url": "http://127.0.0.1:8000/api/workflows/.../"}
```

Poll the status:
```bash
curl http://127.0.0.1:8000/api/workflows/<WORKFLOW_UUID>/ \
  -H "X-Platform-Api-Key: <KEY>"
```

Expected progression: `PENDING → RUNNING_PRE → PATCHING → RUNNING_POST → PASSED`
(Takes about 5–6 seconds with TC001 + TC002 at default delays.)

---

### Scenario 2 — Pre-test failure (TC003 fails, POST skipped)

```bash
curl -X POST http://127.0.0.1:8000/api/workflows/ \
  -H "Content-Type: application/json" \
  -H "X-Platform-Api-Key: <KEY>" \
  -d '{
    "product_id": "<PRODUCT_UUID>",
    "pre_test_case_ids": ["<TC003_UUID>"],
    "post_test_case_ids": ["<TC001_UUID>"]
  }'
```

Expected: workflow → `FAILED`, POST executions → `SKIPPED`, no patch timestamps.

---

### Scenario 3 — Timeout (TC004 never completes)

```bash
curl -X POST http://127.0.0.1:8000/api/workflows/ \
  -H "Content-Type: application/json" \
  -H "X-Platform-Api-Key: <KEY>" \
  -d '{
    "product_id": "<PRODUCT_UUID>",
    "pre_test_case_ids": ["<TC004_UUID>"],
    "post_test_case_ids": ["<TC001_UUID>"]
  }'
```

Expected: TC004 execution → `TIMED_OUT` after `EXECUTION_TIMEOUT_SECONDS` (default 30 s),
then workflow → `FAILED`.

---

### Scenario 4 — Multiple pre-tests (mixed pass/fail)

```bash
curl -X POST http://127.0.0.1:8000/api/workflows/ \
  -H "Content-Type: application/json" \
  -H "X-Platform-Api-Key: <KEY>" \
  -d '{
    "product_id": "<PRODUCT_UUID>",
    "pre_test_case_ids": ["<TC001_UUID>", "<TC003_UUID>"],
    "post_test_case_ids": ["<TC001_UUID>"]
  }'
```

Expected: TC001 passes, TC003 fails → workflow `FAILED` when both are terminal.

---

### Inspecting executions

```bash
curl http://127.0.0.1:8000/api/workflows/<WORKFLOW_UUID>/executions/ \
  -H "X-Platform-Api-Key: <KEY>"
```

---

## Running Tests

```bash
# UTTT platform tests
python manage.py test uttt

# Task API tests
python manage.py test tasks

# Both
python manage.py test
```

Verbose output:

```bash
python manage.py test uttt --verbosity=2
```

---

## Day-to-Day Workflow

### Linux terminal layout

| Terminal | Process |
|---|---|
| 1 | `python manage.py runserver 0.0.0.0:8000` |
| 2 | `python manage.py run_worker` |
| 3 | `python mock_service/manage.py runserver 0.0.0.0:8001` |
| 4 | `python mock_service/manage.py run_mock_worker` |

### After pulling new code

```bash
cd ~/path/to/uttt-poc
git pull
source venv/bin/activate

# If uttt/models.py changed:
python manage.py makemigrations uttt
python manage.py migrate

# If mock models changed:
python mock_service/manage.py migrate

# Restart all four processes
```

---

## Environment Variables Reference

### Main project (.env)

| Variable | Required | Default | Description |
|---|---|---|---|
| `SECRET_KEY` | Yes | — | Django cryptographic signing key |
| `DEBUG` | No | `False` | Set `True` in development only |
| `ALLOWED_HOSTS` | No | `localhost,127.0.0.1` | Comma-separated accepted hostnames |
| `DB_NAME` | No | `uttt` | PostgreSQL database name |
| `DB_USER` | No | `pg` | PostgreSQL username |
| `DB_PASSWORD` | Yes | — | PostgreSQL password |
| `DB_HOST` | No | `127.0.0.1` | Database host |
| `DB_PORT` | No | `5432` | Database port |
| `PLATFORM_API_KEY` | Yes | — | Required in `X-Platform-Api-Key` header |
| `UTTT_BASE_URL` | No | `http://127.0.0.1:8000` | Platform URL (for building callback URLs) |
| `EXECUTION_TIMEOUT_SECONDS` | No | `30` | Seconds before non-terminal executions are timed out |
| `WORKER_POLL_INTERVAL_SECONDS` | No | `3` | Worker sleep between cycles |
| `WORKER_MAX_DISPATCH_RETRIES` | No | `3` | Max dispatch attempts before FAILED |
| `WORKER_HTTP_TIMEOUT_SECONDS` | No | `10` | HTTP timeout for outbound dispatch calls |
| `WORKER_STALE_DISPATCH_SECONDS` | No | `60` | Age at which a SENDING dispatch is considered stale |
| `PRODUCT_DEMO_API_KEY` | Yes | — | API key sent to mock service; must match `MOCK_API_KEY` |
| `PRODUCT_DEMO_CALLBACK_SECRET` | Yes | — | Callback key from mock service; must match `UTTT_CALLBACK_API_KEY` |

### Mock service (mock_service/.env)

| Variable | Required | Default | Description |
|---|---|---|---|
| `MOCK_API_KEY` | Yes | — | API key required in `X-Api-Key` from UTTT worker |
| `UTTT_CALLBACK_API_KEY` | Yes | — | Key sent in `X-Callback-Api-Key` to UTTT; must match `PRODUCT_DEMO_CALLBACK_SECRET` |
| `ALLOWED_CALLBACK_URLS` | No | `http://127.0.0.1:8000` | UTTT base URLs the mock service may call back |
| `TC002_DELAY_SECONDS` | No | `3.0` | Completion delay for TC002 |
| `MOCK_WORKER_POLL_INTERVAL_SECONDS` | No | `2` | Mock worker sleep between cycles |
| `CALLBACK_MAX_RETRIES` | No | `5` | Max callback delivery attempts |
| `CALLBACK_HTTP_TIMEOUT_SECONDS` | No | `10` | HTTP timeout for callback delivery |

---

## Important: Development Server Limitations

`python manage.py runserver` is suitable for learning and local testing only — not production.
For production you need Gunicorn + Nginx + a process manager (systemd). Those steps will be
added in a later stage of this project along with Jenkins CI/CD automation.
