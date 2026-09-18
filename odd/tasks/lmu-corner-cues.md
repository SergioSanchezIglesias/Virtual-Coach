# LMU Corner Cues

## Objective
Create a Windows Python MVP that reads Le Mans Ultimate's native shared-memory telemetry and emits configurable audio cues for brake, brake release, and throttle application at stored corner markers.

## Problem and rationale
The driver needs low-distraction, repeatable braking and exit references while driving LMU. The MVP must remain read-only with respect to the game and have a testable core independent of a running LMU session.

## Scope
- Python package with deterministic marker/cue state machine.
- JSON profiles identified by circuit and vehicle/class.
- LMU native shared-memory adapter using `pyLMUSharedMemory` when installed.
- Windows beep output and a polling CLI.
- Tests, sample profile, requirements, and setup documentation.

## Constraints
- Windows-only runtime target.
- Read LMU native `LMU_Data`; do not install or depend on the legacy rFactor 2 plugin.
- No input sent to LMU.
- Avoid duplicate cues across polling frames and reset correctly on a new lap/session.
- TDD mode: disabled (no existing project configuration or test runner); use focused ordinary checks.
- Delivery strategy: feature-branch-chain, selected by the user after T1 reached 358 authored lines. Each subsequent work unit stays as a separate commit on `feature/lmu-corner-cues`.

## Tasks

- [x] **T1 — Build the cue domain and profile format**
  - Route: delegated (`gentle-ai-worker`); trigger: multi-file write.
  - Add deterministic marker/profile types and a lap-aware cue engine.
  - Add focused unit tests for order, one-shot behavior, and lap reset.
  - Acceptance: marker progression produces `BRAKE`, `RELEASE_BRAKE`, and `THROTTLE` exactly once per lap.
  - Checks: `python -m unittest discover -s tests -v`.
  - Evidence: writer check and independent verification passed: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v` (11 tests) and a `PYTHONPATH=src` API smoke test on Python 3.9.6. Python >=3.9 compatibility corrected without changing cue behavior.

- [x] **T2 — Add LMU reader, audio output, and runnable CLI**
  - Route: delegated (`gentle-ai-worker`); trigger: multi-file write.
  - Add an adapter over `pyLMUSharedMemory`, local-player lookup, polling loop, and Windows audio sink.
  - Acceptance: CLI can connect to LMU when the optional dependency is installed; missing telemetry/dependency fails with an actionable message.
  - Checks: `python -m unittest discover -s tests -v`; `python -m lmu_corner_cues --help`.
  - Evidence: independent recheck passed: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v` (25 tests). The CLI help check passed. Live LMU/Windows sound validation is intentionally recorded as a manual acceptance check for T3.

- [ ] **T3 — Provide a sample profile and operating guide**
  - Route: delegated (`gentle-ai-worker`); trigger: multi-file write.
  - Add a documented sample profile and explain LMU setup, calibration and limitations.
  - Acceptance: a user can install, configure, and run the MVP without source inspection.
  - Checks: `python -m lmu_corner_cues --help`; JSON parse check for the sample profile.
  - Evidence: pending.

## Progress
- Feature branch: `feature/lmu-corner-cues`.
- T1 committed as `04974dc feat(lmu): add corner cue engine` (358 authored lines).
- T2 is in progress.

## Next step
Delegate T2 with bounded runtime surfaces.
