# LMU Corner Cues

A Windows Python MVP that reads Le Mans Ultimate (LMU) native telemetry and plays three sounds at stored lap-distance markers. It never sends driving inputs to the game. **These are fixed references, not braking advice or an adaptive coach.**

## Set up on your Windows LMU PC

Use Python **3.9 or newer**. Open PowerShell in this project's directory:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m lmu_corner_cues --help
```

The package itself has no runtime dependencies. Live telemetry additionally requires the optional upstream [**pyLMUSharedMemory**](https://github.com/TinyPedal/pyLMUSharedMemory) package in the same environment. With Git installed:

```powershell
.\.venv\Scripts\python.exe -m pip install "git+https://github.com/TinyPedal/pyLMUSharedMemory.git"
```

The adapter expects `from pyLMUSharedMemory import lmu_data` and `lmu_data.SimInfo()` exposing `LMUData`. No upstream revision is pinned here; follow upstream requirements for Python compatibility and native bindings.

### Enable native LMU telemetry

Use LMU's **native shared-memory output (`LMU_Data`)**. In current LMU builds, enable **Settings → Gameplay → Enable Plugins**, then restart LMU. If that setting differs in your installed version, consult its current telemetry settings. **Do not install the legacy rFactor 2 shared-memory plugin for this application.** A running menu alone is insufficient: enter a driving session with a local player.

## Configure and launch

Copy [`profiles/example.json`](profiles/example.json) to your own profile file. Its `example-track`, `example-vehicle`, and 100/150/200-meter markers are **fictitious, not calibrated for any track or car**. The example intentionally will not match a real session.

With a calibrated profile matching your current session, run:

```powershell
.\.venv\Scripts\python.exe -m lmu_corner_cues profiles\my-track-car.json
```

Optionally append `--interval 0.02` (the default polling interval, in seconds; must be finite and positive). Stop with **Ctrl+C**. Restart the CLI when changing sessions or profiles. The program has no connected banner, telemetry display, profile recorder, or hot reload.

### Profile schema

JSON must contain only the fields below; duplicate keys and unknown fields are rejected.

| Field | Meaning |
|---|---|
| `circuit` | Required non-empty string matching native `mTrackName` after surrounding whitespace is stripped. |
| `vehicle` | Optional non-empty string matching either `mVehicleName` or `mVehicleClass`. Omit it or use `null` to allow any vehicle. |
| `markers` | Required non-empty array of corner objects in distance order. |
| `markers[].name` | Required unique, non-empty corner label. |
| `markers[].BRAKE` | Absolute lap distance in meters for the brake sound. |
| `markers[].RELEASE_BRAKE` | Absolute lap distance in meters for the release sound. |
| `markers[].THROTTLE` | Absolute lap distance in meters for the throttle sound. |

Distances are finite, non-negative numbers, not strings or booleans. Each corner requires `BRAKE < RELEASE_BRAKE < THROTTLE`; the next corner's `BRAKE` must be strictly beyond the previous corner's `THROTTLE`. Split start/finish-spanning sequences into a representable profile rather than using decreasing distances. The loader does not check track length or whether a marker is safe.

Identifiers are case-sensitive native strings, not necessarily game-menu labels. Mismatch errors show the actual track, vehicle, or class received. Correct the circuit first, then the vehicle if necessary; matching a class does not calibrate distances for every car in that class.

### Cue meanings

| Cue | Windows beep | Intended reference |
|---|---|---|
| `BRAKE` | Low: 440 Hz, 120 ms | Start braking. |
| `RELEASE_BRAKE` | Descending pair: 880 then 660 Hz, 60 ms each | Release the brake. |
| `THROTTLE` | High: 1320 Hz, 120 ms | Apply throttle. |

These meanings describe the stored reference, not a command you must follow. Sounds are fixed in this MVP; only positions are profile-configurable.

## Calibrate safely

1. Use a private practice session, a known track/car/setup, and conservative driving. Establish safe references visually before using audio.
2. Obtain native lap-distance readings (`mLapDist`, meters from the lap origin) using a compatible telemetry viewer/logger. This CLI does not record distances; do not estimate meters from screen coordinates or treat the example as a baseline.
3. Record brake, release, and throttle positions for each corner. Edit a copy of the example with the exact native identifiers and ordered distances.
4. Start the CLI before the first marker, drive a controlled lap, and compare the sounds with your intended references. Stop before editing, then restart and retest. Tune conservatively for polling and sound latency.
5. Recalibrate after changes to car, setup, fuel, tires, weather, or track conditions. Keep a backup of each known profile.

## Manual Windows/LMU validation

**No live LMU/Windows sound validation was run on this development host.** Parsing and CLI help checks do not prove native connectivity or audible playback.

Perform this acceptance scenario on the Windows PC:

1. Start LMU with native shared memory enabled.
2. Enter a driving session with a local player on the intended track and car.
3. Run the CLI command above with an **actual matching, calibrated profile**, not the illustrative example.
4. Confirm native connection: the CLI must not report a dependency, `LMU_Data`, local-player, or profile-mismatch error. Since there is no connection banner, also confirm that driving through the known markers produces telemetry-triggered sounds; silence alone is not proof of connection.
5. Confirm **all three sounds** in order: low brake tone, descending brake-release pair, high throttle tone. Verify they occur at the expected distances, do not repeat on subsequent polling frames, and recur on the next lap.
6. Stop with Ctrl+C. Record the LMU version, upstream dependency revision, profile, and observed outcome before relying on this setup.

## Troubleshooting

| Symptom/error | Action |
|---|---|
| `No module named lmu_corner_cues` | Install the project and run it with the same virtual-environment Python. |
| `Install the optional pyLMUSharedMemory dependency...` | Install the upstream package in this environment and check its native-binding requirements. |
| `Cannot open LMU_Data...` | Use Windows, enable LMU native shared memory, and enter a driving session; restart the CLI. |
| `LMU telemetry has no valid local player...` | Enter the car in an active session; check upstream/game API compatibility and restart. |
| Profile circuit/vehicle `does not match...` | Use the exact received identifier printed in the error and a profile calibrated for that combination. |
| Missing file, invalid JSON, or marker validation error | Check the path, JSON syntax, exact schema keys, unique names, and strictly ordered numeric distances. |
| `Polling interval must be...` | Supply a finite positive number such as `--interval 0.02`. |
| `Audio playback requires Windows...` | Run on the Windows LMU PC; help and profile parsing can work elsewhere. |
| No sound or late sounds | Check Windows audio output/volume, that distances are reached, and that the process has not exited. Reversing or a distance rollback silences cues until the lap counter changes. |

Runtime failures stop the CLI rather than reconnecting automatically. Correct the problem and restart.

## Safety and limitations

- Keep your eyes on the track. Never adjust files or read the terminal while driving. Test at a comfortable volume and stop using cues if distracting or incorrect.
- Cues depend only on lap count and distance, not speed, grip, traffic, pedals, or whether the car is on a racing lap. There is no pit, pause, replay, or hazard filtering.
- Starting mid-lap emits **all already-reached cues**, potentially a burst of stale instructions. Skipped telemetry frames also catch up reached cues. Start before your first marker and ignore stale bursts.
- Cues fire once per reported lap. A distance decrease within the same lap suspends them until the lap identifier changes. Session changes are not independently detected: restart the CLI for each new session.
- Windows beeps block polling while playing; scheduling and telemetry latency can delay cues. This is not a real-time or safety-critical system.
- Shared-memory compatibility depends on the game and upstream library. Live connectivity, native-plugin setup, and sound routing require the manual validation above; no performance or driving-safety guarantee is provided.
