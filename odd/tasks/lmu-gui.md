# LMU Corner Cues GUI

## Objective
Provide a Windows Tkinter GUI as the normal LMU Corner Cues workflow while preserving the CLI as a diagnostic and automation interface.

## Problem and rationale
The existing CLI directly coordinates probing, one-lap recording, interactive profile confirmation, and cue playback. A GUI needs reusable, non-interactive and cancellable orchestration services so it does not duplicate domain logic or block the Tk event loop.

## Scope
- Add an application-service layer for session probing, recording, draft/profile persistence, profile discovery, and cue runtime lifecycle.
- Add a Tkinter GUI command and worker-to-main-thread event delivery.
- Preserve existing CLI behavior through the shared services where practical.
- Add focused GUI/service tests and GUI-first Spanish README guidance.

## Constraints
- Windows-only Tkinter; no new dependencies.
- LMU access remains read-only.
- No GUI interaction is required while the user drives.
- Drafts remain unverified until explicit confirmation.
- Never silently overwrite drafts or profiles.
- Existing untracked `.gitignore` and `docs/` content is outside this feature except the user-provided GUI prompt.

## Delivery
- Strategy: chained PRs (user-selected). Slice 1: T1 services (`a4516e4`); Slice 2: GUI lifecycle and controls (T2–T3); Slice 3: documentation/final verification (T4).
- Forecast: exceeds 400 authored changed lines across the branch; split into the recorded review slices.
- TDD: off; source is no explicit project/session configuration or user request. Verification runner: `python -m unittest discover -s tests -v`.

## Tasks
- [x] T1 — Introduce cancellable application services and refactor the CLI to use them where appropriate. Route: delegated; trigger: multi-file write. Evidence: `a4516e4` (`feat: add cancellable cue application services`); independent verification passed 69 tests with `python3`; `git diff --check` passed. The `python` alias is absent, and native risk assessment was unavailable because the local Gentle AI binary is missing. Rationale: reusable cancellable services keep GUI callbacks thin without duplicating domain behavior.
- [x] T2 — Implement the Tkinter window, state model, worker queue, and safe shutdown. Route: delegated; trigger: multi-file write. Evidence: `fca613e` (`feat: add Tkinter cue lifecycle`); independent verification passed 77 tests with `python3` and `git diff --check`. Thread-start failure recovery is covered with deterministic retry/close tests. Windows/Tk/LMU validation remains pending; native risk assessment was unavailable because the local Gentle AI binary is missing. Rationale: the GUI owns threading and presentation state while domain services own operations.
- [x] T3 — Add draft review/edit/explicit confirmation, confirmed-profile selection, and cue controls. Evidence: `65d4ca3`; independent verification passed 87 tests and whitespace check after lossless unchanged-distance rendering was added. Live Windows/Tk/LMU/audio validation remains pending.
- [x] T4 — Document the Spanish GUI-first workflow and run final checks. Evidence: 87 tests pass; `PYTHONPATH=src python3 -m lmu_corner_cues --help` passes; GUI launch correctly reports its Windows/Tkinter requirement on this host. README qualifies cancellation at the persistence boundary; live Windows/LMU/audio validation remains pending.

## Acceptance criteria
- `python -m lmu_corner_cues gui` launches without LMU running.
- The complete session → record → review → save → drive flow needs no operational CLI commands or JSON editing after GUI launch.
- Recording/playback never block the Tk event loop and incompatible actions are disabled.
- Closing the GUI stops workers and LMU resources safely.
- Existing CLI and tests remain functional.

## Progress
Created 2026-09-19. T1–T4 complete; automated headless verification passed, while Windows/LMU/audio manual validation remains pending.

## Next step
Run the manual Windows/LMU validation checklist before relying on cues on track.
