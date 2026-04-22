# MedX — AI-Native Electronic Health Record
<img width="3191" height="978" alt="Gemini_Generated_Image_yjxw0dyjxw0dyjxw (2)" src="https://github.com/user-attachments/assets/11339c5c-45fb-4d17-a293-71fb8820f113" />

MedX is a lightweight, AI-powered EHR system for general medical use. It ingests clinical documents (PDFs, scanned images), extracts structured data using LLMs, reconciles that data against the patient record, and surfaces everything through a clinician-facing web UI and a patient self-service portal.

> **Status:** R&D / internal MVP. Synthetic data only. HIPAA boundary work (PHI scrubbing before cloud LLM calls) is deferred to Phase 4a.

---

## Table of Contents

1. [Features](#features)
2. [Architecture](#architecture)
3. [Tech Stack](#tech-stack)
4. [Project Structure](#project-structure)
5. [Setup & Installation](#setup--installation)
6. [Configuration](#configuration)
7. [Running the App](#running-the-app)
8. [Login URLs](#login-urls)
9. [AI Pipeline](#ai-pipeline)
10. [Patient Portal](#patient-portal)
11. [API Reference](#api-reference)
12. [Database](#database)
13. [Development Guide](#development-guide)
14. [Known Issues & Tech Debt](#known-issues--tech-debt)

---

## Features

### Clinician Side
- **Patient Registry** — demographics, problems, medications, allergies, observations, AI summary
- **Document Ingestion** — PDF and image upload, OCR via configurable engine (pypdf / OpenRouter / Ollama)
- **AI Extraction Pipeline** — classify → extract → persist → reconcile → summarize (real-time status via SSE)
- **Reconcile Flags** — auto-fill safe fields, flag identity/clinical conflicts with severity tiers
- **Document Viewer** — original file + OCR text + structured extraction side-by-side
- **AI Chat Assistant** — floating widget with patient-context-aware answers
- **Audit Log** — every mutating request logged with user/tenant attribution
- **Token Usage Dashboard** — LLM call log with cost visibility per model/role

### Patient Portal
- **Self-registration** — links to existing patient record by email, or creates a stub
- **Doctor-initiated registration** — doctor creates portal account from patient detail page
- **Health Records** — read-only view of problems, medications, observations, allergies, AI summary
- **Document Upload** — patient uploads documents that enter the same AI pipeline
- **Appointment Booking** — patient requests slots; doctor confirms/cancels from patient detail
- **Secure Messaging** — bidirectional patient ↔ doctor thread with unread badges
- **Patient AI Chat** — chatbot scoped to the patient's own health data

---

## Architecture

```
Browser (HTMX + Tailwind)
        │
        ▼
FastAPI (app/main.py)
  ├── Web Routes      /patients/ui/*, /documents/ui/*, /dashboard, /portal/*
  ├── REST API        /patients, /documents, /auth, /chat
  ├── SSE Stream      /documents/{id}/events  ← real-time pipeline updates
  └── Middleware      AuditMiddleware (every mutating request logged)
        │
  ┌─────┴──────────────────────────────────────────┐
  │                                                │
  ▼                                                ▼
PostgreSQL (SQLAlchemy async ORM)         In-Process Queue (asyncio)
(SQLAlchemy async ORM)                     │
                                           ▼
                                   Worker Pool (concurrency=2)
                                     ├── ocr_process
                                     └── extract_document
                                           │
                                    AI Pipeline (app/ai/agents/)
                                     ├── classify_document
                                     ├── extract_document       ← unified (known types)
                                     ├── plan_and_extract       ← dynamic (unknown types)
                                     ├── persist_extraction
                                     ├── reconcile_patient_profile
                                     └── summarize_patient
                                           │
                                    OpenRouter / Ollama
                                    (OpenAI-compatible API)
```

### Event Flow (real-time pipeline status)

```
Worker emits step event
      │
      ▼
EventBus (in-memory, keyed by document_id)
      │
      ▼
SSE endpoint /documents/{id}/events
      │
      ▼
Browser EventSource → JS updates pipeline chips without page reload
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, FastAPI |
| Frontend | HTMX 2.x, Tailwind CSS (CDN) |
| Database | PostgreSQL 16 |
| ORM | SQLAlchemy 2.x async |
| Migrations | Alembic |
| Auth | JWT (python-jose), bcrypt |
| Queue | In-process asyncio (→ arq/Redis in Phase 5) |
| File storage | Local disk (→ S3 in Phase 5) |
| AI provider | OpenRouter (cloud) or Ollama (local) |
| OCR | pypdf (text-layer) / OpenRouter VLM / Ollama VLM (configurable) |
| Real-time | Server-Sent Events (sse-starlette) |

---

## Project Structure

```
medx/
├── app/
│   ├── main.py                  # FastAPI app factory, lifespan, exception handlers
│   ├── config.py                # Pydantic Settings — all env vars
│   ├── security.py              # JWT + bcrypt helpers
│   ├── deps.py                  # FastAPI dependency injection (auth, session)
│   ├── logging.py               # Structured logging config (structlog)
│   │
│   ├── api/                     # JSON REST endpoints
│   │   ├── auth.py              # /auth/login, /auth/register
│   │   ├── chat.py              # POST /chat (clinician AI chat)
│   │   ├── documents.py         # /documents CRUD + raw file serving
│   │   ├── extractions.py       # /extractions read
│   │   ├── health.py            # GET /healthz
│   │   └── patients.py          # /patients CRUD
│   │
│   ├── ai/
│   │   ├── client.py            # OpenRouterClient — async LLM calls, retry, JSON parse
│   │   ├── models.py            # ModelRole enum + model ID resolution
│   │   ├── errors.py            # AI-specific exception types
│   │   ├── schemas/             # JSON schemas for LLM output validation
│   │   └── agents/
│   │       ├── router.py        # Pipeline orchestrator (classify→extract→persist→…)
│   │       ├── classify.py      # Document type classification
│   │       ├── extract.py       # Unified extractor — all known doc types (_CONFIGS dict)
│   │       ├── plan_extract.py  # Dynamic 2-step extractor for unknown doc types
│   │       ├── extract_patient_info.py  # Patient demographics from document text
│   │       ├── persist.py       # Write extracted data to clinical tables
│   │       ├── profile_reconcile.py     # Auto-fill + conflict detection
│   │       ├── summarize.py     # Generate patient.ai_summary
│   │       ├── chat.py          # Chat answer generation
│   │       └── doctype.py       # DocType enum
│   │
│   ├── audit/
│   │   └── middleware.py        # Starlette middleware — logs all mutating requests
│   │
│   ├── db/
│   │   ├── base.py              # SQLAlchemy declarative base + PrimaryKeyMixin
│   │   ├── session.py           # Async engine + session factory
│   │   ├── models/
│   │   │   ├── tenant.py        # Tenant, User (roles: admin/doctor/patient)
│   │   │   ├── patient.py       # Patient demographics + clinical summary fields
│   │   │   ├── clinical.py      # Problem, Medication, Observation, Allergy, Encounter
│   │   │   ├── document.py      # Document, Extraction
│   │   │   ├── reconcile.py     # ReconcileFlag (severity/tier/resolved_by)
│   │   │   ├── portal.py        # Appointment, Message (patient portal)
│   │   │   ├── audit.py         # AuditLog
│   │   │   ├── llm_call_log.py  # LLMCallLog (token usage tracking)
│   │   │   └── summary.py       # Summary
│   │   └── repositories/        # Tenant-scoped async repository pattern
│   │
│   ├── events/
│   │   └── bus.py               # In-process SSE event bus
│   │
│   ├── ingestion/
│   │   ├── store.py             # DocumentStore abstraction (LocalDiskStore / S3)
│   │   └── ocr/
│   │       ├── pipeline.py      # OCR dispatch — routes to engine set by OCR_ENGINE
│   │       ├── pypdf_engine.py  # Text-layer PDF extraction (default)
│   │       ├── openrouter_engine.py  # Vision OCR via OpenRouter cloud VLM
│   │       └── ollama_engine.py # Vision OCR via local Ollama VLM
│   │
│   ├── queue/
│   │   ├── asyncio_queue.py     # Bounded worker pool, job registry, startup recovery
│   │   └── jobs.py              # Job handler registrations
│   │
│   ├── schemas/                 # Pydantic request/response schemas
│   │
│   ├── validation/
│   │   ├── upload.py            # Pre-LLM file validation (MIME, size, page count)
│   │   └── extraction.py        # Deterministic extraction checks (Tier 1 validation)
│   │
│   └── web/
│       ├── routes.py            # HTMX web routes (clinician UI)
│       ├── portal_routes.py     # Patient portal routes (/portal/*, /patient/*)
│       └── templates/           # Jinja2 templates (Tailwind CSS)
│           ├── base.html        # Clinician nav shell
│           ├── portal/          # Patient portal templates
│           └── ...
│
├── alembic/                     # Database migrations
├── scripts/
│   └── create_admin.py          # CLI to create admin user + tenant
├── .env.example                 # Environment variable template
└── pyproject.toml               # Project metadata + dependencies
```

---

## Setup & Installation

### Option 1 — Docker (recommended, zero local deps)

```bash
git clone <repo>
cd medx
cp .env.example .env
# Edit .env — set AI_PROVIDER and the matching model settings (see Configuration below)
docker compose up --build
```

The `app` container:
- Waits for Postgres to pass its healthcheck
- Runs `alembic upgrade head` automatically
- Starts on `http://localhost:8000`

Uploads are persisted in a named Docker volume (`uploads`). Postgres data is in `postgres-data`.

To stop and clean up:
```bash
docker compose down          # keep volumes
docker compose down -v       # also delete DB and uploads
```

---

### Option 2 — Local Python + Postgres

#### Prerequisites

- Python 3.12+
- Docker (for Postgres) **or** a local Postgres 16 instance
- An [OpenRouter](https://openrouter.ai) API key **or** a local [Ollama](https://ollama.ai) instance

#### Install

```bash
git clone <repo>
cd medx
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

#### Start Postgres

```bash
# Spin up just the database container (no app container)
docker compose up postgres -d
```

#### Environment & migrations

```bash
cp .env.example .env
# Edit .env — set AI_PROVIDER and the matching model settings (see Configuration below)
alembic upgrade head
```

---

## Configuration

All configuration is via environment variables or a `.env` file. There are no hardcoded fallbacks — missing required variables cause the app to fail at startup with a clear error. See `.env.example` for the full template.

### Core Settings

| Variable | Required | Default | Description |
|---|---|---|---|
| `APP_ENV` | No | `dev` | Application environment: `dev` or `prod` |
| `APP_DEBUG` | No | `true` | Enable debug mode (verbose logging, detailed errors) |

### Database

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | **Yes** | — | Async SQLAlchemy connection string. Examples:<br>• PostgreSQL: `postgresql+asyncpg://user:pass@host:5432/db`<br>• SQLite: `sqlite+aiosqlite:///./medx.db` |

### Authentication & Security

| Variable | Required | Default | Description |
|---|---|---|---|
| `JWT_SECRET` | **Yes** | — | Secret key for JWT token signing. Must be unique per deployment. Use a long random string (32+ chars). |
| `JWT_ALGORITHM` | No | `HS256` | JWT signing algorithm |
| `JWT_EXPIRE_MINUTES` | No | `60` | Session token lifetime in minutes |

### Seed Admin Account

These variables create the initial admin account on first startup. All are required.

| Variable | Required | Description |
|---|---|---|
| `SEED_TENANT_NAME` | **Yes** | Tenant name for the auto-created admin (e.g., `MedX`) |
| `SEED_ADMIN_EMAIL` | **Yes** | Admin email address |
| `SEED_ADMIN_PASSWORD` | **Yes** | Admin password — **change before production deployment** |
| `SEED_ADMIN_NAME` | **Yes** | Admin display name |

### AI Provider Configuration

MedX supports two AI providers: **OpenRouter** (cloud) and **Ollama** (local). Set `AI_PROVIDER` to choose which one to use for the extraction pipeline.

| Variable | Required | Default | Description |
|---|---|---|---|
| `AI_PROVIDER` | No | `openrouter` | AI provider: `openrouter` (cloud LLM) or `ollama` (local LLM) |

#### OpenRouter Settings

Required when `AI_PROVIDER=openrouter` **or** `OCR_ENGINE=openrouter`.

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENROUTER_API_KEY` | **Yes*** | — | API key from [openrouter.ai/keys](https://openrouter.ai/keys) |
| `OPENROUTER_MODEL` | **Yes*** | — | Model ID for all AI tasks. Examples:<br>• `deepseek/deepseek-chat-v3:free`<br>• `anthropic/claude-3.5-sonnet`<br>• `google/gemini-2.0-flash-exp:free` |
| `OPENROUTER_BASE_URL` | No | `https://openrouter.ai/api/v1` | OpenRouter API base URL |
| `OPENROUTER_APP_TITLE` | No | `MedX` | App identifier sent in API headers |
| `OPENROUTER_TIMEOUT_S` | No | `90.0` | Request timeout in seconds |

*Required only when using OpenRouter

#### Ollama Settings

Required when `AI_PROVIDER=ollama` **or** `OCR_ENGINE=ollama`.

| Variable | Required | Default | Description |
|---|---|---|---|
| `OLLAMA_MODEL` | **Yes*** | — | Model name for all AI tasks. Examples:<br>• `llama3.2:latest`<br>• `gemma4:e4b`<br>• `qwen2.5:14b` |
| `OLLAMA_BASE_URL` | No | `http://localhost:11434/v1` | Ollama API base URL (OpenAI-compatible endpoint) |
| `OLLAMA_VISION_MODEL` | No | — | **Only used when `OCR_ENGINE=ollama`.** Separate multimodal model for vision OCR. If not set, falls back to `OLLAMA_MODEL`. Use this when you want a different model for OCR than for extraction. Examples:<br>• `llava:latest`<br>• `llava-phi3:latest`<br>• `minicpm-v:latest` |
| `OLLAMA_TIMEOUT_S` | No | `120.0` | Request timeout in seconds |

*Required only when using Ollama

### OCR Engine Configuration

Controls how documents are converted to text. Choose based on your document types and performance needs.

| Variable | Required | Default | Description |
|---|---|---|---|
| `OCR_ENGINE` | No | `pypdf` | OCR engine selection:<br><br>• **`pypdf`** — Fast text-layer extraction. Works for digital PDFs with embedded text. No AI required. **Recommended for most use cases.**<br><br>• **`openrouter`** — Vision-based OCR using OpenRouter VLM. Handles scanned documents and images. Requires `OPENROUTER_API_KEY` and `OPENROUTER_MODEL`. Slower but works on any image/PDF.<br><br>• **`ollama`** — Vision-based OCR using local Ollama VLM. Requires `OLLAMA_MODEL` (or `OLLAMA_VISION_MODEL`). Use a multimodal model like `llava` or `minicpm-v`. |

**Performance comparison:**
- `pypdf`: ~1-2 seconds per document (fastest)
- `ollama`: ~10-30 seconds per page (depends on model and hardware)
- `openrouter`: ~5-15 seconds per page (depends on model and API latency)

**When to use each:**
- Use `pypdf` for modern digital PDFs (lab reports, discharge summaries, etc.)
- Use `ollama` or `openrouter` for scanned documents, handwritten notes, or images

### Document Storage

| Variable | Required | Default | Description |
|---|---|---|---|
| `DOCUMENT_STORE` | No | `local` | Storage backend: `local` (filesystem) or `s3` (AWS S3) |
| `LOCAL_STORE_PATH` | No | `./uploads` | Directory path for local file storage (used when `DOCUMENT_STORE=local`) |

### Background Queue

| Variable | Required | Default | Description |
|---|---|---|---|
| `QUEUE_BACKEND` | No | `inprocess` | Queue backend: `inprocess` (asyncio-based, single worker) or `arq` (Redis-backed, planned for Phase 5) |
| `QUEUE_MAX_CONCURRENCY` | No | `2` | Number of parallel AI pipeline workers. Higher values process more documents simultaneously but use more memory and API quota. |

---

### Configuration Examples

#### Example 1: OpenRouter (Cloud) with PyPDF OCR

```bash
# Core
APP_ENV=dev
DATABASE_URL=postgresql+asyncpg://medx:medx@localhost:5432/medx

# Auth
JWT_SECRET=your-secret-key-here-make-it-long-and-random

# Seed admin
SEED_TENANT_NAME=MedX
SEED_ADMIN_EMAIL=admin@medx.com
SEED_ADMIN_PASSWORD=change-me-in-production
SEED_ADMIN_NAME=Admin User

# AI: OpenRouter
AI_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-v1-xxxxx
OPENROUTER_MODEL=deepseek/deepseek-chat-v3:free

# OCR: Fast text extraction
OCR_ENGINE=pypdf
```

#### Example 2: Ollama (Local) with Vision OCR

```bash
# Core
APP_ENV=dev
DATABASE_URL=sqlite+aiosqlite:///./medx.db

# Auth
JWT_SECRET=your-secret-key-here-make-it-long-and-random

# Seed admin
SEED_TENANT_NAME=MedX
SEED_ADMIN_EMAIL=admin@medx.com
SEED_ADMIN_PASSWORD=change-me-in-production
SEED_ADMIN_NAME=Admin User

# AI: Ollama
AI_PROVIDER=ollama
OLLAMA_BASE_URL=http://192.168.1.100:11434/v1
OLLAMA_MODEL=llama3.2:latest
OLLAMA_VISION_MODEL=llava:latest

# OCR: Vision-based for scanned documents
OCR_ENGINE=ollama
```

#### Example 3: Hybrid (OpenRouter AI + Ollama OCR)

```bash
# Core
APP_ENV=prod
DATABASE_URL=postgresql+asyncpg://medx:medx@db:5432/medx

# Auth
JWT_SECRET=production-secret-key-32-chars-minimum

# Seed admin
SEED_TENANT_NAME=MedX
SEED_ADMIN_EMAIL=admin@medx.com
SEED_ADMIN_PASSWORD=SecurePassword123!
SEED_ADMIN_NAME=Admin User

# AI: OpenRouter for extraction pipeline
AI_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-v1-xxxxx
OPENROUTER_MODEL=anthropic/claude-3.5-sonnet

# OCR: Local Ollama for vision OCR
OCR_ENGINE=ollama
OLLAMA_BASE_URL=http://ollama-server:11434/v1
OLLAMA_VISION_MODEL=minicpm-v:latest

# Performance
QUEUE_MAX_CONCURRENCY=4
```

---

## Running the App

**Docker** — migrations + server start automatically:
```bash
docker compose up --build
```

**Local Python** — run migrations once, then start the server:
```bash
alembic upgrade head

# Development (auto-reload)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Production
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

> **Note:** Use `--workers 1` because the queue and event bus are in-process singletons. Switch to arq/Redis (Phase 5) before scaling to multiple workers.

---

## Login URLs

| Role | Login URL | Notes |
|---|---|---|
| Doctor | `/doctor/login` | Requires tenant name + email + password |
| Admin | `/admin/login` | Requires tenant name + email + password |
| Patient | `/patient/login` | Email + password only (no tenant name) |

`/login` redirects to `/doctor/login` by default.

### Creating the First Admin Account

The admin account is created automatically on first startup using the `SEED_*` variables from `.env`. All four (`SEED_TENANT_NAME`, `SEED_ADMIN_EMAIL`, `SEED_ADMIN_PASSWORD`, `SEED_ADMIN_NAME`) are required — the app will not start without them.

To create additional admin accounts via CLI:

```bash
docker exec -it medx-app python -m scripts.create_admin
```

Prompts for tenant name, email, full name, and password. Creates the tenant if it doesn't exist.

### Creating a Doctor Account

```
GET /register  →  creates a new tenant + doctor account
```

### Creating a Patient Account

**Option A — Doctor creates it:**
Open any patient's detail page → click **"+ Register Portal Account"** → enter email + temporary password.

**Option B — Patient self-registers:**
Patient goes to `/patient/register` → enters the email their doctor has on file → account auto-links to the existing patient record.

---

## AI Pipeline

Every uploaded document flows through a 6-step pipeline tracked in real time via SSE:

```
Upload
  │
  ▼
[1] OCR  ─────────────────────────────────────────── Document.ocr_status
  Engine set by OCR_ENGINE:
    pypdf      — text-layer extraction (default, no AI)
    openrouter — vision VLM via OpenRouter (OPENROUTER_MODEL)
    ollama     — vision VLM via Ollama (OLLAMA_MODEL or OLLAMA_VISION_MODEL)
  │
  ▼
[2] Classify ─────────────────────────────────────── pipeline_status.classify
  LLM determines document type:
  lab_panel | imaging_report | discharge_summary | med_list | history_physical | other
  │
  ▼
[3] Extract ──────────────────────────────────────── pipeline_status.extract
  Type-specific LLM call with JSON-schema-enforced output
  Parallel: also extracts patient demographics (profile step prep)
  │
  ▼
[4] Persist ──────────────────────────────────────── pipeline_status.persist
  Writes typed rows: Observation, Medication, Problem, Allergy
  Runs reconciliation: duplicate/conflict detection → ReconcileFlag rows
  │
  ▼
[5] Profile ──────────────────────────────────────── pipeline_status.profile
  Auto-fills safe patient fields (phone, email, blood_type, …)
  Flags identity/clinical conflicts with severity (critical/warning/info)
  │
  ▼
[6] Summarize ────────────────────────────────────── pipeline_status.summarize
  Generates patient.ai_summary from all clinical data
```

### Document Types

| Type | Extracts |
|---|---|
| `lab_panel` | observations (label, value, unit, loinc_hint, flag) |
| `imaging_report` | modality, findings, impression, measurements |
| `discharge_summary` | diagnoses, medications, observations, dates |
| `med_list` | medications (name, dose, frequency, route, status) |
| `history_physical` | vitals, problems, medications, allergies, chief_complaint, assessment, plan |
| `other` / unknown | dynamic plan+extract — LLM self-generates extraction prompt; stored as JSONB |

### Reconciliation Severity

| Category | Condition | Severity |
|---|---|---|
| Identity (name, DOB, MRN) | conflict | `critical` |
| Blood type | conflict | `critical` |
| Sex | conflict | `warning` |
| Allergies summary | conflict | `warning` |
| Any safe field | auto-fill | `info` |

---

## Patient Portal

The portal lives at `/portal/*` with `/patient/login` and `/patient/register` as canonical entry points.

### Routes

| Path | Description |
|---|---|
| `GET /patient/login` | Patient login page |
| `GET /patient/register` | Self-registration |
| `GET /portal/dashboard` | Health summary: conditions, meds, labs, appointments |
| `GET /portal/records` | Full health records (all clinical data) |
| `GET /portal/documents` | Document list + upload |
| `GET /portal/appointments` | Appointment list + booking form |
| `GET /portal/messages` | Patient ↔ doctor message thread |
| `POST /portal/chat` | Patient AI chat (scoped to own records) |

### Doctor-side portal routes (on patient detail page)

| Path | Description |
|---|---|
| `POST /patients/ui/{id}/create-portal-account` | Doctor creates patient login |
| `POST /portal/doctor/messages/{patient_id}/reply` | Doctor sends message to patient |
| `POST /portal/doctor/appointments/{id}/confirm` | Confirm appointment |
| `POST /portal/doctor/appointments/{id}/cancel` | Cancel appointment |

---

## API Reference

### Authentication

```
POST /auth/login      { tenant_name, email, password }  →  { access_token }
POST /auth/register   { tenant_name, email, password, full_name }  →  { access_token }
```

### Patients

```
GET    /patients              List patients (tenant-scoped)
POST   /patients              Create patient
GET    /patients/{id}         Get patient
PATCH  /patients/{id}         Update patient
DELETE /patients/{id}         Delete patient
```

### Documents

```
GET    /documents                         List documents
POST   /documents                         Upload document (multipart)
GET    /documents/{id}                    Get document metadata
DELETE /documents/{id}                    Delete document
GET    /documents/{id}/raw                Serve raw file
GET    /documents/{id}/events             SSE stream of pipeline events
POST   /documents/ui/{id}/reprocess       Re-run extraction pipeline
```

### Extractions

```
GET /extractions?document_id={id}    List extractions for a document
```

### Chat

```
POST /chat         { question, patient_id? }  →  { answer }   (clinician, tenant-scoped)
POST /portal/chat  { question }               →  { answer }   (patient, own data only)
```

---

## Database

### Schema Overview

```
Tenant ──< User (role: admin|doctor|patient, patient_id FK →Patient)
Tenant ──< Patient ──< Document ──< Extraction
                    ──< Problem
                    ──< Medication
                    ──< Observation
                    ──< Allergy
                    ──< ReconcileFlag
                    ──< Appointment
                    ──< Message
Tenant ──< AuditLog
Tenant ──< LLMCallLog
```

### Migrations

```bash
# Apply all pending migrations
alembic upgrade head

# Create a new migration
alembic revision --autogenerate -m "description"

# Show current state
alembic current
```

---

## Development Guide

### Adding a New Document Type

Unknown document types are handled automatically by the dynamic fallback extractor (`plan_extract.py`) — no code changes needed. To promote a frequently-seen type to a first-class clinical type with typed DB rows:

1. Add value to `DocType` enum in `app/ai/agents/doctype.py`
2. Create JSON schema in `app/ai/schemas/{type}.schema.json`
3. Add entry to `_CONFIGS` dict in `app/ai/agents/extract.py` (system prompt + schema name)
4. Add `_persist_{type}` function in `app/ai/agents/persist.py` and wire it into `persist_extraction`
5. Add rendering block in `app/web/templates/document_viewer.html`
6. Add schema name to `_DOC_TYPE_TO_SCHEMA` in `app/validation/extraction.py`
7. Update `app/ai/schemas/classify.schema.json` doc_type enum

### Adding a New LLM Role

1. Add value to `ModelRole` in `app/ai/models.py`
2. Call the agent with that role — it automatically uses `OPENROUTER_MODEL` (or `OLLAMA_MODEL` when `AI_PROVIDER=ollama`). No per-role config needed.

### Swapping AI Provider

Change `AI_PROVIDER` in `.env` — no code changes needed.

| `AI_PROVIDER` | Model used |
|---|---|
| `openrouter` | `OPENROUTER_MODEL` for all roles |
| `ollama` | `OLLAMA_MODEL` for all roles |

OCR is independent: set `OCR_ENGINE` separately (`pypdf` / `openrouter` / `ollama`).

### Re-extracting All Documents

Go to `/admin/usage` → click **"↻ Re-extract All Documents"**. This re-queues classify → extract → persist → summarize for every document with completed OCR.
