# LMU Onboarding Without JSON or External Pip Dependency

## Objective
Make `pip install .` sufficient for LMU Corner Cues, remove the unusable VCS installation command, and replace JSON-first setup with a guided session, automatic one-lap recording, and stopped configuration review.

## Decisions
- A project-owned native `LMU_Data` adapter, validated against the official LMU shared-memory interface at runtime; no pip installation of `pyLMUSharedMemory`.
- The primary configuration experience is a stopped assistant. It may record a clean lap automatically while the driver drives, then presents/requires confirmation only after the lap.
- JSON remains an internal export format, not a required user input.

## Constraints
- Windows LMU target; read-only access to the game.
- Native mapping layout must be documented with source/attribution and reject incompatible map sizes/versions safely.
- Do not require terminal interaction while the driver is driving.
- TDD mode: disabled; ordinary focused tests and independent verification are mandatory because native assessment is unavailable in this environment.
- Delivery strategy: feature-branch-chain. Current branch: `feature/lmu-corner-cues`.

## Tasks

- [x] **T1 — Bundle a project-owned native LMU reader**
  - Route: delegated (`gentle-ai-worker`); trigger: multi-file write.
  - Replace the optional `pyLMUSharedMemory` import with a local Windows shared-memory reader exposing the required session snapshot and pedal fields.
  - Record source attribution and compatibility behavior; fail safely when LMU is absent/incompatible.
  - Checks: focused native-adapter tests and full unit suite.
  - Evidence: writer and independent recheck passed 33 tests. Player association, sentinel IDs, pedal range, and lap/distance validation are covered. Live Windows/LMU compatibility is explicitly deferred to T4 because synthetic fixtures cannot prove the producer ABI.

- [x] **T2 — Add session probe and one-lap recording**
  - Route: delegated (`gentle-ai-worker`); trigger: multi-file write.
  - Add commands that show observed circuit/vehicle/lap distance and record pedal transitions for one clean lap without user input while driving.
  - Checks: fake-reader recorder/probe tests and CLI help.
  - Evidence: independent verification passed: 45 tests, CLI help, and unchanged Git state. Continuity-only drafts are explicitly unverified/non-calibrated and cannot drive cues.

- [x] **T3 — Add stopped profile wizard and rewrite onboarding**
  - Route: delegated (`gentle-ai-worker`); trigger: multi-file write.
  - Turn recorded candidates into a confirmed profile through a stopped wizard; update README so a user never needs to edit JSON or install upstream Git code.
  - Checks: wizard/profile tests, README command consistency, CLI help.
  - Evidence: independent verification passed: 56 tests, CLI help, no unexpected mutations or bytecode. The README now uses only `pip install .`; live acceptance remains T4.

- [ ] **T4 — Perform live Windows/LMU acceptance validation**
  - Route: user-operated manual validation; no terminal interaction while driving.
  - Validate clean installation, native map connection, observed identifiers, one-lap recording, confirmed wizard profile, and the three cue sounds.
  - Evidence: pending; this is the only task that can establish compatibility with the installed LMU build.

## Acceptance
- A clean Windows environment installs with `pip install .`, with neither Git nor `pyLMUSharedMemory` needed.
- A live LMU session can show exact observed identifiers and record a clean-lap candidate without terminal interaction during driving.
- The stopped wizard saves a valid profile only after user confirmation.
- Existing driving cues still run from the saved profile.

## Progress
- T1 committed as `c704281 feat(lmu): bundle native telemetry reader`.
- T2 committed as `2bb1dbf feat(lmu): add session probe and lap recorder`.
- T3 is complete pending its work-unit commit.

## Next step
Commit T3 and perform T4 manual Windows/LMU acceptance validation.
