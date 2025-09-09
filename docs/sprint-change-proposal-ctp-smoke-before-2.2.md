# Sprint Change Proposal — Real CTP Connectivity Smoke Test (before Story 2.2)

Date: 2025-09-09
Triggering Stories: 2.1 (done), planned 2.2 (not started)
Requested by: Team (to reduce technical debt)

## 1) Identified Issue Summary

- Problem: Risk that real CTP connectivity (binary deps, account auth, network reachability, supervisor/retry behavior) surfaces late during Story 2.2 or later, increasing integration debt and rework.
- Change: Insert a short, real-account connectivity smoke test between 2.1 and 2.2 to validate login and supervised lifecycle with actual CTP front servers.
- Objective: De-risk by validating 2.1’s adapter against a real CTP environment without implementing 2.2 features (subscriptions/async bridge).

## 2) Context & Evidence (Checklist §1)

- Real account: Available (production account). Testing during trading hours is possible.
- Platform: Ubuntu Linux. Team can install `vnpy_ctp` via `uv add vnpy_ctp` (local-only execution; not in CI).
- Network: Direct internet egress to CTP MD/TD front servers; no VPN required.
- Secrets & Safety: Use env vars only; do not log secrets (current `to_dict_safe()` masks sensitive values).
- Scope for this change: Validate connect/login + supervised retry behavior + structured logs within ~2 minutes runtime. No market data subscription or event bridging (that is Story 2.2).

Statuses (Checklist §1):
- [x] Identify Triggering Story (2.2 depends on solid connectivity; 2.1 implemented adapter)
- [x] Define the Issue (risk of late discovery of environment/auth/deps issues)
- [x] Assess Initial Impact (low scope addition; medium risk mitigated early)
- [x] Gather Evidence (account present; env/OS feasible; runtime window OK)

## 3) Epic Impact Assessment (Checklist §2)

- Current Epic (Epic 2): Still valid. Add a small interim story before 2.2.
- Future Epics: No changes required.
- Sequence: Insert a “2.1a: Real CTP Connectivity Smoke Test” between 2.1 and 2.2.

Statuses (Checklist §2):
- [x] Current epic can proceed with a minor addition
- [x] Future epics unaffected; no reordering beyond adding 2.1a
- [x] Summarized epic impact: Minimal; schedule insert only

## 4) Artifact Conflict & Impact (Checklist §3)

- PRD: No core requirement changes; optionally note early live-connectivity validation in QA/test approach.
- Architecture: No structural change; confirm external integration note for CTP is via vn.py plugin (not REST). No new diagrams needed.
- Frontend Spec: N/A.
- Other Artifacts: Add a note in test strategy about “local-only live connectivity checks” and secret handling reinforcement.

Statuses (Checklist §3):
- [x] PRD unaffected (optional QA note)
- [x] Architecture consistent (adapter design already defined)
- [N/A] Frontend
- [x] Test strategy additions (local-only, secrets, structured logs)

## 5) Path Forward Evaluation (Checklist §4)

- Option 1 — Direct Adjustment/Integration: Insert a minimal smoke test using real account to validate 2.1 behavior. Effort low, risk reduction high. Recommended.
- Option 2 — Rollback: Not applicable.
- Option 3 — PRD MVP Re-scope: Not needed.

Selected Path: Option 1 (Direct Adjustment) — add a small interim story and local-only test script.

## 6) Specific Proposed Edits

1. Add Story 2.1a: “Real CTP Connectivity Smoke Test” (between 2.1 and 2.2)
   - Story: As a Developer, I want to verify real CTP login and supervised retry behavior using the implemented adapter and a real account, so that we de-risk integration before building the sync-to-async bridge.
   - Acceptance Criteria:
     - AC1: A local-only script or entrypoint runs the adapter’s real `gateway_connect` integration for up to 2 minutes and exits cleanly.
     - AC2: Successful login path is observed in structured logs (no secrets in logs).
     - AC3: Failure path produces retries with exponential backoff and new session per attempt; logs include {attempt, reason, next_backoff}.
     - AC4: No credentials are committed or leaked; all supplied via env vars.
   - Out of Scope: Subscriptions, async event bridge, queue handoff (deferred to 2.2/2.3).

2. Test Strategy & Security Notes (docs/architecture/test-strategy-and-standards.md)
   - Add a subsection: “Local-only Live CTP Connectivity Checks” stating:
     - Executed on a developer-controlled machine only; not in CI.
     - Secrets via environment (uppercase names accepted by settings class; case-insensitive).
     - Logs must remain structured and must not include secret values; reference `to_dict_safe()` usage.

3. QA Gate (new)
   - Add `docs/qa/gates/2.1a-ctp-real-connectivity.yml` after execution with PASS/CONCERNS/FAIL based on observed behavior (up to QA).

4. Developer Run Instructions (for the new story; not to be committed with secrets)
   - Dependencies: `vnpy` + `vnpy_ctp` installed locally (e.g., `uv add vnpy vnpy_ctp`). Ensure system libraries required by CTP plugin are present for Ubuntu.
   - Environment variables (examples):
     - `CTP_BROKER_ID`, `CTP_USER_ID`, `CTP_PASSWORD`, `CTP_MD_ADDRESS`, `CTP_TD_ADDRESS`, `CTP_APP_ID`, `CTP_AUTH_CODE`
   - Smoke execution (example outline):
     - Implement a local-only runner (e.g., `scripts/ctp_connect_smoke.py`) that wires a real `gateway_connect` using vn.py CTP plugin, then calls `CTPGatewayAdapter.connect()`, sleeps/monitors up to ~120s, and `disconnect()`.
     - Success: login observed; clean shutdown; no secret leaks; if disconnection occurs, retries and new session names observed.

## 7) High-Level Action Plan

1) Add Story 2.1a to backlog (PO/SM) — Priority: Must-do before 2.2.
2) Implement local-only smoke runner and minimal wiring (Dev) — 0.5–1 day.
3) Execute during trading hours with real account on Ubuntu (Dev) — < 2 minutes.
4) Record results and create QA Gate file (QA) — PASS/CONCERNS/FAIL with rationale.
5) Proceed to Story 2.2 only if Gate = PASS or acceptable CONCERNS.

## 8) Success Criteria

- Demonstrated successful login or well-characterized failure with structured logs.
- Supervisor behavior verified: retries with exponential backoff, new session per attempt.
- No secret leakage; environment-only configuration.
- Execution ≤ 2 minutes and exits cleanly.

## 9) Approval

- Recommended Path: APPROVE adding Story 2.1a and executing local-only smoke test prior to 2.2.
- Stakeholders: PO/SM to add story; Dev to implement/run; QA to gate.
