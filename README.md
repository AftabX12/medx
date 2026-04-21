# MedX — AI-Native Electronic Health Record

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
- **Document Ingestion** — PDF and image upload, OCR via pypdf / OpenRouter VLM / Marker
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
| OCR | pypdf (text-layer) + OpenRouter VLM + Marker (local) |
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
│   │       ├── pipeline.py      # OCR job: try pypdf → vision VLM → Marker
│   │       ├── pypdf_engine.py  # Text-layer PDF extraction
│   │       ├── openrouter_engine.py  # Vision LLM OCR
│   │       └── marker_engine.py # Local Marker fallback
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
# Edit .env — add your OPENROUTER_API_KEY at minimum
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
# Edit .env — at minimum set OPENROUTER_API_KEY
alembic upgrade head
```

---

## Configuration

All configuration is via environment variables (or a `.env` file). See `.env.example` for defaults.

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://medx:medx@localhost:5433/medx` | Async SQLAlchemy URL |
| `SECRET_KEY` | *(required)* | JWT signing key — change in production |
| `JWT_EXPIRE_MINUTES` | `60` | Session token lifetime |
| `AI_PROVIDER` | `openrouter` | `openrouter` or `ollama` |
| `OPENROUTER_API_KEY` | — | Required when `AI_PROVIDER=openrouter` |
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | Ollama API base |
| `OLLAMA_MODEL` | `gemma4:e4b` | Model used for all roles when Ollama |
| `AI_MODEL_CLASSIFY` | `meta-llama/llama-3.3-70b-instruct:free` | Classification model |
| `AI_MODEL_EXTRACT` | `nvidia/nemotron-super-120b-instruct:free` | Extraction model |
| `AI_MODEL_VISION_OCR` | `nvidia/nemotron-nano-12b-vl:free` | Vision OCR model |
| `AI_MODEL_SUMMARIZE` | `nvidia/nemotron-super-120b-instruct:free` | Summarization model |
| `AI_MODEL_CHAT` | `nvidia/nemotron-super-120b-instruct:free` | Chat model |
| `DOCUMENT_STORE` | `local` | `local` or `s3` |
| `LOCAL_STORE_PATH` | `./document_store` | Root directory for local storage |
| `OCR_ENGINE` | `openrouter_vision` | `pypdf`, `openrouter_vision`, or `marker` |
| `OCR_MAX_PAGES` | `30` | Maximum PDF pages accepted |
| `QUEUE_MAX_CONCURRENCY` | `2` | Parallel AI pipeline workers |
| `APP_ENV` | `dev` | `dev` or `prod` (affects cookie security) |

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
  Try pypdf (text-layer PDF)
  → fallback: OpenRouter vision VLM (scanned docs)
  → fallback: local Marker
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
2. Add corresponding setting in `app/config.py`
3. Set model ID in `.env`

### Swapping AI Provider

Change `AI_PROVIDER=ollama` in `.env` — no code changes needed. All model roles route to `OLLAMA_MODEL`.

### Re-extracting All Documents

Go to `/admin/usage` → click **"↻ Re-extract All Documents"**. This re-queues classify → extract → persist → summarize for every document with completed OCR.
