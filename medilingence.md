# MedX — Lightweight AI-Native EHR (Living PRD / Plan)

> **Status:** this is the authoritative implementation plan for MedX. It supersedes the earlier MedDiligence M&A-DD PRD that previously lived in this file. Keep it in sync with the code: when scope, architecture, or phasing changes, update this document in the same commit.

---

## Progress snapshot (as of 2026-04-21)

| Phase | Status | Notes |
|---|---|---|
| Phase 0 — Foundations | ✅ Done | Models, repositories, auth, audit middleware |
| Phase 1a — Document upload | ✅ Done | `DocumentStore` abstraction, upload endpoint |
| Phase 1b — Text-PDF extraction (pypdf) | ✅ Done | pypdf engine, OCR package |
| Phase 1.5 — Tenant dashboard | ✅ Done | Counts, recent uploads, needs-attention, storage |
| Phase 1c — Real OCR (OpenRouter vision + Marker) | ✅ Done | Vision VLM + local Marker fallback |
| Phase 2 — Extraction → structured clinical tables | ✅ Done | classify → extract → persist → summarize pipeline |
| Phase 2 — Reconcile flags | ✅ Done | Auto-fill safe fields, flag conflicts, apply/dismiss UI |
| Phase 3 core — Clinician UI | ✅ Done | Patient detail, document viewer, edit/delete, chat widget |
| **Phase 3.1 — Clinical review enhancement** | ✅ Done | Severity tiers, dashboard flags widget, activity log, confidence badges, flag inspector, edit-apply |
| **Phase 2.5 — Shift-left validation tier** | ✅ Done | Pre-LLM deterministic checks — `app/validation/` |
| **Phase 3.2 — Patient Portal** | ✅ Done | Self-registration, health records, documents, appointments, messaging, AI chat, sidebar layout |
| **Extractor consolidation** | ✅ Done | 5 separate extractors → single `extract.py` driven by `_CONFIGS` dict |
| **Tier 3 dynamic extraction** | ✅ Done | `doc_type=other` now runs `plan_extract.py` (2-step LLM plan+extract) instead of skipping |
| **UI redesign** | ✅ Done | All templates: dark mode, sidebar layout, Tailwind throughout |
| Phase 4a — HIPAA anonymization boundary | ⏳ Not started | PHI scrubbing before cloud LLM calls |
| **Phase 4b — Real-time SSE event bus** | ✅ Done | EventBus singleton, SSE endpoint, EventSource in viewer |
| **Phase 4c — Token usage tracking** | ✅ Done | LLMCallLog, context-var attribution, /admin/usage |
| Phase 5a — Hash-chain audit log | ⏳ Not started | Tamper-evident AuditLog |
| Phase 5b — Manual vs auto pipeline mode | ⏳ Not started | Gate extraction on human approval |
| Phase 5c — Infrastructure hardening | ⏳ Not started | S3, Redis/arq, BAA pathway |

### Known tech debt
- `.venv` shebangs point at stale `/home/mahesh/mediligence/.venv/bin/python3`. Workaround: invoke via `.venv/bin/python -m <tool>`. Fix: recreate venv.
- Free-tier OpenRouter model IDs drift. If a model 404s, run `GET https://openrouter.ai/api/v1/models?supported_parameters=free` and update `.env`.
- `pipeline_status` JSONB column is append-only; no GC yet.
- Docker must be installed via apt (`docker-ce`), not snap — snap confinement causes `permission denied` on container stop.

---

## Context

- **Shape**: lightweight EHR with an AI report-analysis layer
- **Users**: clinicians (cardiology, confirmed in [pyproject.toml](pyproject.toml))
- **Intent**: internal R&D first, commercialize later — multi-tenant-ready from day 1
- **Stage**: R&D — synthetic data only. HIPAA boundary work deferred to Phase 4a.
- **Team**: solo builder; no clinician partner yet (blocker for Phase 3 exit — see §5)

---

## 1. Specialty

Cardiology. Locked. Extraction prompts in `app/ai/prompts/` are cardiology-tuned. Confirm before adding a second specialty.

---

## 2. Scope

### In (R&D MVP)
- Patient registry: demographics, problem list, meds, allergies, observations ✅
- Document ingestion: PDF + image uploads, pypdf + VLM + Marker OCR ✅
- Extraction pipeline: classify → extract → persist → reconcile → summarize ✅
- Profile reconciliation: auto-fill safe fields, flag identity/clinical conflicts ✅
- Reconcile flags UI: apply / dismiss per flag ✅
- Patient detail: demographics, documents, observations, meds, problems, AI summary ✅
- Document viewer: original + OCR text + structured extractions side-by-side ✅
- AI chart-prep summary (`patient.ai_summary`) ✅
- AI chat assistant (floating widget) ✅
- Audit logging (middleware) ✅
- Severity tiers + tier classification on reconcile flags ✅
- Reconcile flag stats on dashboard (open/critical counts) ✅
- Activity / audit log page (`/activity`) ✅
- Confidence surfacing in structured extraction pane ✅
- Flag inspector: source document context inline on review ✅
- Field correction ("Edit & Apply") on flag resolver ✅

### Explicitly out (MVP)
- Ambient scribe, e-prescribing, billing/RCM
- Lab/imaging order integrations (HL7/FHIR)
- Multi-tenant UI (DB is ready; app single-tenant for now)

---

## 3. Architecture

### Tech stack
- **Backend**: FastAPI (Python 3.11+)
- **DB**: Postgres 16 (via Docker Compose; `asyncpg` driver; Alembic migrations)
- **File storage**: local disk (`LocalDiskStore`) → S3 (same `DocumentStore` interface)
- **Queue**: in-process `asyncio.Queue`, bounded worker pool (concurrency=2) → arq/Redis (Phase 5c)
- **AI layer**: OpenRouter free tier (OpenAI-compatible). Model IDs are env-driven — no code change to swap:
  - Classify: `meta-llama/llama-3.3-70b-instruct:free`
  - Extract / Summarize / Chat: `nvidia/nemotron-3-super-120b-a12b:free`
  - Vision OCR: `nvidia/nemotron-nano-12b-vl:free`
- **OCR**: pypdf (text-layer) → OpenRouter VLM (scanned) → Marker (local opt-in extra)
- **Frontend**: HTMX + Tailwind CDN (dark mode via `darkMode: 'class'`). React only if UX demands it.
- **Auth**: FastAPI + `python-jose` JWT; session cookies for web UI; Clerk/Auth0 later
- **Deployment**: Docker Compose (`medx-app` + `medx-postgres`); `docker-entrypoint.sh` runs Alembic then uvicorn

### Data model (current + Phase 3.1 additions)

```
Tenant, User                              ✅
Patient                                   ✅ (all demographic + clinical summary fields)
Document                                  ✅ (ocr_status, ocr_text, doc_type, pipeline_status)
Extraction                                ✅ (field_type, value_normalized, confidence, model)
Observation, Medication, Problem, Allergy ✅
ReconcileFlag                             ✅ severity/tier/resolved_by added (Phase 3.1)
AuditLog                                  ✅ (prev_hash/row_hash added in Phase 5a)
LLMCallLog                                ✅ (Phase 4c)
```

`ReconcileFlag` additions (Phase 3.1):
- `severity: str` — `"critical"` | `"warning"` | `"info"` (drives UI colour + sort order)
- `tier: int` — `1` = deterministic check, `2` = LLM-derived (drives badge label)
- `resolved_by: str | None` — `"clinician_apply"` | `"clinician_dismiss"` | `"system"` (audit trail)

Severity rules (assigned in `profile_reconcile.py`):
| Field category | Condition | Severity |
|---|---|---|
| Identity (name, DOB, MRN) | any conflict | critical |
| Identity (sex) | conflict | warning |
| Clinical (blood_type) | conflict | critical |
| Clinical (allergies_summary) | conflict | warning |
| Contact / insurance / address | conflict | info |
| Any field | auto-fill (no existing value) | info |

---

## 4. AI pipeline

### Document pipeline (fully wired)

```
upload → ocr_process (queue)
       → [pypdf | openrouter_vision | marker]
       → extract_document (queue, on ocr_status=ok)
           → classify_document (LLM)
           → [known type]  extract_document(doc_type, text)   ← unified extract.py (_CONFIGS dict)
             [unknown type] plan_and_extract(text)            ← plan_extract.py (2-step LLM)
           → persist_extraction / persist_dynamic_extraction
               → Observation/Medication/Problem/Allergy rows  (known types only)
               → JSONB audit row in extractions               (all types)
           → reconcile_patient_profile (auto-fill + conflict flagging with severity)
           → summarize_patient (LLM → patient.ai_summary)
```

Pipeline status tracked per step in `Document.pipeline_status` JSON column.

**Extraction tiers:**
- **Tier 1 (known clinical types)**: `lab_panel`, `imaging_report`, `discharge_summary`, `med_list`, `history_physical` — fixed prompt + JSON schema → typed clinical DB rows. Validated with `jsonschema` before persist.
- **Tier 3 (dynamic fallback)**: any unrecognized `doc_type=other` (pharmacy receipts, OPD slips, referral letters, etc.) — LLM self-generates extraction prompt → JSONB-only persist, doc_type updated to LLM-inferred label (e.g. `"pharmacy_receipt"`). Zero code changes needed for new types.

### Profile reconciliation
- **Auto-fill** (safe when DB empty): phone, email, address, blood_type, primary_physician, insurance, emergency contact, allergies_summary
- **Review-only** (always flagged even if DB empty): given_name, family_name, date_of_birth, sex, mrn
- Each flag now carries `severity` + `tier` (see §3 severity table)

### Chat assistant
- Floating widget, logged-in users only
- Context: patient roster + document list + status breakdown
- `max_attempts=2`, rate-limit errors surface as human-readable message

### Evals
- Synthetic 50-doc dataset v1 under `app/ai/evals/fixtures/datasets/v1/`
- Exit gate: `overall_f1 >= 0.85` in `tests/test_phase2_exit.py`

---

## 5. Closing the clinician gap (blocker for Phase 3 final exit)

- Recruit one cardiologist for 30-min sessions before Phase 3.1 ships (Reddit r/medicine, local med school, Tegus/GLG)
- UX gate: no Phase 3 "done" without one clinician running through 3 patients end-to-end

---

## 6. Phased build plan

### Phase 0 — Foundations ✅
Register tenant, log in, create patient via API, all writes audited.

### Phase 1 — Ingestion ✅
Upload PDF → `ocr_status=ok`, raw text stored, extraction job enqueued.

### Phase 1.5 — Tenant dashboard ✅
Counts, recent uploads, needs-attention, storage — all tenant-scoped.

### Phase 2 — Extraction + Reconcile ✅
classify → extract → persist → reconcile profile → summarize. Extraction F1 ≥ 0.85 on synthetic test set.

### Phase 3 core — Clinician UI ✅ (exit pending clinician review)
Patient detail, document viewer, edit/delete, reconcile flag apply/dismiss, AI chat.
Remaining: clinician partner walkthrough, timeline view, encounter notes.

---

### Phase 2.5 — Shift-left validation tier ✅
Deterministic pre-checks *before* any LLM call — burns zero API budget.

**Shipped (`app/validation/`):**
- `validate_upload()` — MIME allowlist (PDF/PNG/JPG/TIFF), size ≤ 25 MB, PDF page count ≤ `ocr_max_pages`; wired into `routes.py` (replaced inline checks)
- `validate_extraction_output()` — JSON schema validation of LLM payload against canonical schema before DB write; wired into `router.py`
- Min OCR text length guard in `pipeline.py` — skips extraction dispatch if text < 20 chars
- Patient-to-tenant ownership check in `router.py` before any LLM call

**Exit criterion met**: `tests/test_validation.py` — 16 tests green; full suite 38/38 green.

---

### Phase 3.1 — Clinical review enhancement ✅

Learned from MortIQ (mortgage-lite) pattern analysis. Six deliverables shipped together.

#### 3.1.1 — Severity + tier on ReconcileFlag ✅
**Why**: today all flags look the same — a name mismatch and a phone number mismatch are visually identical. Severity drives urgency; tier tells the clinician whether the flag came from a deterministic rule or an LLM.

**Changes:**
- Alembic migration: add `severity VARCHAR(16)`, `tier INTEGER`, `resolved_by VARCHAR(32)` to `reconcile_flags`
- `ReconcileFlag` model: three new mapped columns
- `profile_reconcile.py`: assign severity + tier per field (see §3 severity table); set `resolved_by` in resolve route
- `patient_detail.html`: flag banner colour = severity (red=critical, amber=warning, slate=info); tier badge ("Rule" vs "AI")

**Exit criterion**: uploading a document with a name conflict creates a flag with `severity="critical"`, `tier=2`; a phone conflict creates `severity="info"`.

#### 3.1.2 — Reconcile flag stats on dashboard ✅
**Why**: the dashboard currently has zero clinical signal. A clinician's first question is "what needs my attention?" — open/critical flags answer that.

**Changes:**
- `DashboardRepository`: `open_flag_count() -> int`, `critical_flag_count() -> int`
- `routes.py` `/dashboard` handler: pass counts
- `dashboard.html`: new "Flags" stats card (red dot if critical > 0)

**Exit criterion**: dashboard shows accurate open/critical flag counts; zero when no flags; link goes to first patient with open flags.

#### 3.1.3 — Activity / audit log page ✅
**Why**: `AuditLog` is written on every mutation but there's no UI. Clinicians need to see who did what — operationally useful now, HIPAA-required later.

**Changes:**
- `routes.py`: `GET /activity` — query `AuditLog` descending, paginated (50/page), filter by action type
- `app/web/templates/activity.html`: table — Time / Actor / Action / Resource / Path; search + type filter

**Exit criterion**: `/activity` renders a paginated log of all mutations; filtering by action type works; cross-tenant isolation enforced.

#### 3.1.4 — Confidence surfacing in document viewer ✅
**Why**: `Extraction.confidence` is stored but invisible. A 0.42 confidence score on a medication dose should alarm the clinician; 0.97 should reassure them.

**Changes:**
- `document_viewer.html` structured pane: per-extraction confidence badge (green ≥ 0.8, amber 0.5–0.79, red < 0.5)
- For lab panel: per-observation abnormal flag already shown; add overall extraction confidence header
- `ExtractionRepository` or route: ensure `confidence` is passed through to the template (currently it is via `extractions` list)

**Exit criterion**: structured pane shows coloured confidence badge on each extraction; low-confidence extractions visually distinguished.

#### 3.1.5 — Flag inspector: source document context ✅
**Why**: clicking Apply/Dismiss today has no context — the clinician can't see *why* the flag was raised. The source document should be visible alongside the conflict.

**Changes:**
- `patient_detail.html`: make each reconcile flag card expandable (click to expand) — show an `<iframe>` of `/documents/{document_id}/raw` (PDF) or `<img>` (image) in a collapsible section below the flag detail
- `routes.py` `/patients/ui/{patient_id}`: pass `document` objects keyed by `document_id` so template can render the preview
- No new endpoint needed — raw file endpoint already exists

**Exit criterion**: clicking a flag card expands an inline preview of the source document; PDF loads in iframe; "collapse" button hides it.

#### 3.1.6 — Field correction ("apply with edit") on flag resolver ✅
**Why**: "Apply" blindly uses the document's value; "Dismiss" keeps the existing value. The correct answer is sometimes *neither* — the clinician may want to type a corrected value (e.g., normalise a DOB format, fix a typo in a phone number). Learned from MortIQ's field correction flow.

**Changes:**
- `patient_detail.html`: Add a third button "Edit & Apply" per flag. Clicking it reveals an `<input>` pre-filled with `document_value`; submitting POSTs the corrected value.
- `routes.py` resolve endpoint: accept `action="edit_apply"` + `corrected_value` form field; set the patient field to `corrected_value` instead of `document_value`; log to AuditLog with `action="flag_corrected"`
- Works for `patient_profile` flags only (other resource types deferred)

**Exit criterion**: "Edit & Apply" button reveals editable input; submitting it sets the patient field to the typed value and resolves the flag.

---

### Phase 4 — HIPAA anonymization boundary + real-time events ⏳

Two independent workstreams (can be parallelised).

#### 4a — Anonymization boundary (HIPAA-critical before any real PHI)
- `app/anonymization/` package
- `AnonymizationEngine`: local NER (presidio) scans OCR text → replaces PHI with `{{PATIENT_NAME_1}}` etc.
- Reverse mapping stored ephemerally (in-memory, never persisted), purged after deanonymization
- Pipeline wiring: anonymize before OpenRouter call in `extract_*` agents; deanonymize before writing to DB

**Why ephemeral**: persisting the reverse map alongside anonymized text provides no protection.

Exit criterion: synthetic PHI document passes pipeline; OpenRouter API logs show only pseudonyms.

#### 4b — Real-time SSE event bus
- `app/events/bus.py` — `EventBus` singleton (AsyncQueue per channel)
- Emit `pipeline_step_completed` after each `_set_step` in `router.py`
- `GET /documents/{id}/events` → `text/event-stream`
- Replace htmx polling in `document_viewer.html` with `EventSource`

Exit criterion: pipeline badges update in real time with zero polling.

**✅ Done** — EventBus emits per-step events; `document_viewer.html` always shows all 6 pipeline chips with live colour updates; `pipeline_active` flag drives EventSource activation; upload auto-redirects to document viewer via `HX-Redirect`.

#### 4c — Token usage tracking
- `OpenRouterClient._call` already receives `response.usage`; currently discarded
- New `LLMCallLog(id, tenant_id, document_id, role, model, prompt_tokens, completion_tokens, created_at)` table
- `GET /admin/usage` → per-tenant token totals

Exit criterion: every LLM call produces a `LLMCallLog` row.

---

### Phase 5 — Hardening + commercialize-readiness ⏳

#### 5a — Hash-chain audit log
- Add `prev_hash`, `row_hash` to `AuditLog`
- `row_hash = sha256(prev_hash + action + resource_id + at + metadata_json)`
- `GET /admin/audit/verify` walks chain, returns first broken link

Exit criterion: manually editing an AuditLog row causes `verify` to return a break.

#### 5b — Manual vs auto pipeline mode
- New `Document.pipeline_mode` field: `"auto"` (default) | `"manual"`
- After OCR: if manual, set `pipeline_status.extract = awaiting_approval` and stop
- `POST /documents/{id}/approve-extraction` → enqueue `extract_document`
- Dashboard "needs attention" includes manually-gated docs

Exit criterion: `pipeline_mode=manual` stops after OCR; calling approve triggers extraction.

#### 5c — Infrastructure hardening
- Local storage → S3 (same `DocumentStore` interface)
- In-process queue → arq + Redis (same queue interface)
- Tenant isolation stress test: cross-tenant access attempts at every endpoint
- BAA pathway with OpenRouter or Azure OpenAI when real PHI enters
- SOC 2 documentation groundwork
- Postgres cutover: verify FK cascades on Postgres via Docker Compose test

---

## 7. File manifest

```
app/
  main.py                        ✅
  config.py                      ✅
  deps.py                        ✅
  db/
    models/
      reconcile.py               ✅ + severity/tier/resolved_by (Phase 3.1.1)
      audit.py                   ✅ (prev_hash/row_hash in Phase 5a)
    repositories/
      dashboard.py               ✅ + open_flag_count/critical_flag_count (Phase 3.1.2)
      reconcile.py               ✅
  api/
    auth.py, patients.py         ✅
    documents.py                 ✅
    extractions.py               ✅
    chat.py                      ✅
  ai/
    client.py                    ✅
    models.py                    ✅
    agents/
      classify.py                ✅
      router.py                  ✅ (orchestrates all pipeline steps)
      extract.py                 ✅ unified extractor (_CONFIGS dict, all known doc types)
      plan_extract.py            ✅ dynamic 2-step fallback for unknown doc types
      persist.py                 ✅ + persist_dynamic_extraction for Tier 3
      profile_reconcile.py       ✅ + severity/tier assignment (Phase 3.1.1)
      extract_patient_info.py    ✅
      summarize.py               ✅
      chat.py                    ✅
    evals/                       ✅
  ingestion/ocr/                 ✅
  queue/                         ✅
  validation/                    ✅ (Phase 2.5)
  anonymization/                 ⏳ Phase 4a
  events/                        ✅ (Phase 4b)
  audit/middleware.py            ✅
  web/
    routes.py                    ✅ + /activity route (Phase 3.1.3)
                                    + edit_apply resolve action (Phase 3.1.6)
    templates/
      base.html                  ✅ sidebar layout, dark mode, all roles
      portal/base.html           ✅ sidebar layout (sky accent, patient nav)
      dashboard.html             ✅ + flags stats card (open/critical counts)
      patient_detail.html        ✅ + severity colours + flag inspector + edit-apply
      document_viewer.html       ✅ + confidence badges + dynamic extraction renderer
      activity.html              ✅ paginated audit log, action filter
      admin_home.html            ✅ tenants + users tables
      admin_usage.html           ✅ token usage breakdown
      portal/dashboard.html      ✅ health summary, conditions, meds, labs, appointments
      portal/{records,documents,appointments,messages}.html ✅
alembic/versions/               ✅ all migrations tracked
scripts/
  create_admin.py               ✅ interactive CLI to create admin + tenant
```

---

## 8. Verification plan

- Eval harness `overall_f1 >= 0.85` on synthetic dataset
- Tenant isolation: cross-tenant access blocked at every endpoint
- Clinician partner walkthrough at Phase 3 final exit
- Before real PHI: anonymization verified (4a), audit chain intact (5a)
- Docker smoke test: `docker compose up --build -d` → app healthy at `:8000`

---

## 9. Decisions still open

1. **Clinician partner** — hard blocker for Phase 3 final exit.
2. **Anonymization approach** — presidio (rule-based, no GPU) vs small local NER. Start with presidio + custom cardiology recognizers.
3. **SSE vs WebSocket** — SSE sufficient for pipeline status; WebSocket only if bidirectional real-time needed.
4. **OpenRouter model churn** — if a model 404s twice, add `list_free_models()` (30 LOC) for auto-selection.
5. **HIPAA provider** — when real PHI enters, switch to Azure OpenAI (BAA available) or Anthropic BAA. Architecture: update `openrouter_base_url` + key in `.env`, plus Phase 4a as belt-and-suspenders.
6. **Timeline** — Phase 3.1 is 2–3 days. Phase 2.5 is 1 day. Phase 4 is ~1 week. Phase 5 is ~2 weeks.

---

## 10. Tenant Dashboard (Phase 1.5 — shipped)

Post-login landing page. Counts + recent uploads + needs-attention + storage — all tenant-scoped. Phase 3.1.2 adds a "Flags" clinical signal card.

---

## Maintenance rule

This file is the living plan. When a phase ships or scope shifts, update this document in the same change. A stale plan is worse than no plan.
