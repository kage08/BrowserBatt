# AI Agent Guide for BrowserBatt

BrowserBatt is a macOS browser battery-efficiency benchmark. It drives real installed browsers with the user's current profiles, extensions, cookies, and settings, then records battery, process, and optional `powermetrics` telemetry.

Use this guide when making code changes or running checks in this repository.

---

## Project Layout

```
browserbatt/
├── __init__.py       # Package version (__version__ = "0.1.0")
├── __main__.py       # Entry point for `python -m browserbatt`
├── cli.py            # CLI argument parsing and command dispatch (doctor, smoke, run, analyze)
├── config.py         # Config loading, validation, and dataclasses
├── runner.py         # Benchmark orchestration: run directories, lifecycle, measurement flow
├── browser.py        # Browser app metadata (BrowserSpec) and automation (BrowserController)
├── workloads.py      # Workload phase definitions and browser activity (WorkloadRunner)
├── sampler.py        # Battery/process/power telemetry sampling in background thread
├── analysis.py       # Aggregation, derived metrics, and report generation
├── macos.py          # macOS helpers: power/battery, brightness, process, system tools
└── util.py           # Shared utilities: JSON/CSV I/O, subprocess, time helpers
```

Other notable files:

- `pyproject.toml` — package metadata, entry points (`browserbatt` script), no third-party deps
- `Plan.md` — design rationale and architecture decisions
- `config.example.json` — full benchmark config (5 reps, 720s, all browsers)
- `config.quick-daily.json` / `config.quick-edge-daily.json` — short preset configs
- `runs/` — generated output (treat as local data, never commit)

---

## Key Abstractions

### Config (`browserbatt/config.py`)

All configuration lives in a `BrowserBattConfig` dataclass (nested `MeasurementConfig` and `AutomationConfig`):

```python
MeasurementConfig:
  repetitions: int = 5                # measured reps per browser
  warmup_seconds: int = 360          # 6 min warmup per browser (excluded from stats)
  cooldown_seconds: int = 180         # 3 min settling between runs
  baseline_seconds: int = 600         # 10 min idle baseline (start + end)
  sample_interval_seconds: int = 2     # battery/process sampling cadence
  min_battery_percent: int = 15       # stop if battery drops below
  require_battery_power: bool = True  # refuse to run on AC
  use_powermetrics: bool = True       # attempt powermetrics (requires sudo)
  screen_brightness_percent: int | None = 50
  browser_order: list[str]            # base order for Latin-square rotation

AutomationConfig:
  viewport_width: int = 1440
  viewport_height: int = 900
  typing_cadence_seconds: float = 0.04
  docs_cleanup_policy: str = "record_for_manual_cleanup"
```

Browsers and workloads are validated against `KNOWN_BROWSERS = ("chrome", "safari", "edge", "firefox", "zen")` and `KNOWN_WORKLOADS = ("daily", "media", "reading")`.

`rotated_orders(browsers, repetitions)` generates a Latin-square-style browser execution order to reduce ordering bias across repetitions.

### Browser (`browserbatt/browser.py`)

A `BrowserSpec` (frozen dataclass) maps each key to its app metadata:

```python
BrowserSpec(key, app_name, bundle_path, process_name=None)
BROWSERS["chrome"]  → Google Chrome at /Applications/Google Chrome.app
BROWSERS["safari"]  → Safari at /Applications/Safari.app
BROWSERS["edge"]    → Microsoft Edge at /Applications/Microsoft Edge.app
BROWSERS["firefox"] → Firefox at /Applications/Firefox.app, process_name="firefox"
BROWSERS["zen"]     → Zen at /Applications/Zen.app, process_name="zen"
```

`BrowserController` is the automation facade. Key methods:

| Method | What it does |
|--------|-------------|
| `installed()` | Check if .app bundle exists |
| `quit()` | Gracefully quit (osascript → pkill fallback) |
| `is_running()` | pgrep check |
| `launch_clean()` | Quit → launch with browser-specific args → wait → normalize window → resize |
| `activate()` | Bring to front |
| `close_all_windows()` | Close every window (osascript → Cmd+Opt+W → dismiss dialogs) |
| `open_url(url)` | Set URL via AppleScript (Chrome/Edge) or manual type |
| `new_tab(url)` | Cmd+T, type URL, Enter |
| `switch_to_tab(index)` | Cmd+1-9 |
| `scroll(clicks)` / `page_down(count, delay)` | Scrolling |
| `type_text(text)` / `type_text_slow(text, cadence)` | Keyboard input |
| `play_pause()` | Keystroke "k" (YouTube) |

Chromium-based browsers (Chrome, Edge) receive extra launch args: `--disable-session-crashed-bubble`, `--no-first-run`, `--new-window`, `about:blank`.

### Workloads (`browserbatt/workloads.py`)

`WorkloadRunner` dispatches to named workloads. Each is a generator function that yields events and runs browser interactions:

- **`daily`**: Multi-tab (YouTube + Docs + news + blog + GitHub). Phase split ~30/25/15/15/15%. YouTube gets `autoplay=1` param.
- **`media`**: YouTube-only with `autoplay=1`, active wait with occasional scroll.
- **`reading`**: News + blog + GitHub, no video or Docs. Phase split ~35/30/35%.

`_active_wait(seconds, action)` runs a busy loop until a monotonic deadline, calling the provided action (page_down/scroll/typing) every 0.2s.

`_event(event, **data)` appends timestamped JSONL entries to `events.jsonl`.

### Sampler (`browserbatt/sampler.py`)

`Sampler` runs in a daemon thread. `start()` creates the output directory, launches `powermetrics` (if enabled), and starts the sampling loop. `stop()` joins the thread, stops powermetrics, writes CSVs.

Output files (per run, under `<run-id>/<browser>/<workload>/<rep>/`):
- **`power.csv`**: timestamp, percent, power_source, is_charging, voltage_mv, amperage_ma, instant_watts, *_mah
- **`processes.csv`**: timestamp, pid, ppid, cpu_percent, mem_percent, rss_kb, command
- **`powermetrics.txt`**: raw `powermetrics --samplers cpu_power,gpu_power` output (if sudo available)

Warnings written to `warnings.txt`: power source change during run, battery charging, no watt samples, powermetrics permission errors.

### Runner (`browserbatt/runner.py`)

`run_workload(config, workload, out_root, dry_run=False) -> Path` is the main orchestrator. Exception `LowBatteryStop` halts a run and marks it partial.

**Full run directory structure** (under `runs/<run-id>/`):
```
status.json                  # completed / partial / error
metadata.json               # env: OS, hardware, power, displays, thermal, browsers
effective_config.json       # exact config used (resolved defaults)
events.jsonl                # all events across the entire run
google-docs-cleanup.md      # disposable doc URLs to delete
analysis.json               # aggregate analysis
report.md                   # human-readable report
baseline-start/             # idle baseline measurement
baseline-end/               # idle baseline measurement
<browser>/
  <workload>/
    warmup-01/              # warmup (excluded from stats)
      power.csv, processes.csv, events.jsonl, summary.json,
      run_metadata.json, powermetrics.txt, warnings.txt
    rep-01/ ... rep-05/     # measured repetitions
```

`_preflight()` checks: not on AC power, not charging, battery ≥ min_battery_percent.

`_one_run()`: create dir → log start → launch browser → start sampler → run workload → stop sampler → close browser → summarize → log end.

`estimate_runtime(config, workload)` calculates total seconds = warmups + measured + cooldowns + baselines + launch overhead.

### Analysis (`browserbatt/analysis.py`)

`summarize_run(run_dir)` computes stats from `power.csv`: sample_count, watts_mean/median/min/max, battery percent delta.

`analyze(root)` aggregates all run summaries into `analysis.json`:

```json
{
  "root": "...",
  "baseline_watts": 3.2,
  "results": [{
    "browser": "chrome",
    "workload": "daily",
    "runs": 5, "usable_runs": 5,
    "mean_watts": 8.1, "median_watts": 7.9,
    "stdev_watts": 0.4, "ci95_watts": 0.35,
    "baseline_watts": 3.2,
    "incremental_watts": 4.9,
    "estimated_battery_life_hours": 4.8
  }]
}
```

`write_markdown_report(root, report)` generates a table comparing all browser/workload combinations.

Derived metrics:
- `incremental_watts` = mean_watts - baseline_watts
- `ci95_watts` = `1.96 * stdev / sqrt(n)` (None if n < 2)
- `estimated_battery_life_hours` = `(max_mah * voltage_mv / 1_000_000) / watts`
- warmup runs (dirs starting with "warmup") are excluded from aggregates

### macOS helpers (`browserbatt/macos.py`)

| Function | Purpose |
|----------|---------|
| `command_exists(name)` | Check if command is in PATH |
| `prevent_sleep(reason)` | Context manager, starts `caffeinate -dimsu -w <pid>` |
| `capture_environment()` | Returns dict: OS version, hardware, power, displays, thermal state, browser versions |
| `get_screen_brightness()` | Read brightness via DisplayServices ctypes |
| `set_screen_brightness(percent)` | Write brightness via DisplayServices or keyboard fallback |
| `ensure_screen_brightness(percent, tolerance=2)` | Set and verify; raises if out of tolerance |
| `browser_versions()` | Read CFBundleShortVersionString from app Info.plist |
| `battery_status()` | Returns `BatteryStatus` dataclass from `pmset -g batt` + `ioreg -rn AppleSmartBattery` |
| `process_snapshot(browser)` | Returns list of dicts from `ps` for browser processes |
| `start_powermetrics(path, interval_ms)` | Launch `powermetrics --samplers cpu_power,gpu_power` (prefixes sudo if not root) |
| `stop_process(proc, timeout)` | Gracefully terminate, kill if timeout exceeded |

`BatteryStatus` fields: timestamp, percent, power_source, is_charging, voltage_mv, amperage_ma, instant_watts, current/max/design_capacity_mah.

### Utilities (`browserbatt/util.py`)

| Function | Purpose |
|----------|---------|
| `now_iso()` | ISO timestamp string |
| `run_cmd(args, timeout, check)` | Subprocess runner |
| `write_json(path, data)` | Pretty-printed JSON (dataclass-aware via `_jsonable()`) |
| `append_jsonl(path, data)` | Append JSON lines (no pretty print) |
| `write_csv(path, rows, fieldnames)` | CSV DictWriter |
| `sleep_until(deadline_monotonic, tick)` | Busy-wait loop (max 0.25s sleep) |

---

## Tooling

- Python version: `>=3.11`. No third-party dependencies (pure stdlib).
- Package manager/runtime: `uv`.
- Package metadata: `pyproject.toml`.
- Entry point: `browserbatt` script (installed by pyproject.toml).

Preferred commands for development:

```bash
uv run browserbatt doctor --config config.example.json
uv run browserbatt smoke --browser chrome --workload reading --duration-seconds 90
uv run browserbatt analyze runs/<run-id>
uv run python -m compileall browserbatt          # syntax/type check
```

---

## CLI Commands

| Command | Description |
|---------|-------------|
| `doctor` | Check prerequisites: battery, brightness, browsers, system tools. `--config` path. |
| `smoke` | Short automation test (1 rep, no warmup, no powermetrics). `--browser`, `--workload`, `--duration-seconds N` (default 90), `--out`. |
| `run` | Full benchmark. `--workload` (required), `--browser` (filter), `--config`, `--out`, `--yes` (confirmation). |
| `analyze` | Re-compute analysis + report for existing run. Positional `run_dir`. |

---

## Benchmark Safety

BrowserBatt intentionally interacts with the local machine:

- Full runs close and reopen target browsers.
- Runs use real browser profiles (logged-in sessions, extensions, settings intact).
- Runs set display brightness to configured value (50% default) and verify it.
- Runs start `caffeinate -dimsu` to prevent sleep during measurement.
- Battery-mode runs can take hours (full `daily` ~7.5h across 5 browsers).
- `powermetrics` requires `sudo`; recommended: `sudo -v` before running.
- Auto-stops if battery drops below `min_battery_percent`; marks run `partial` in `status.json`.

**Do not start long runs unless the user explicitly asks.** Prefer `doctor`, `smoke`, static checks, or `analyze` while developing.

---

## Common Tasks

### Add or adjust a browser

1. Add/update the `BrowserSpec` in `BROWSERS` dict in `browserbatt/browser.py`. Use `process_name` if the process name differs from the app name (see Firefox/Zen examples).
2. If the browser needs special launch args, update `_open_for_clean_launch()` (Chromium-based browsers already get `--disable-session-crashed-bubble`, `--no-first-run`, `--new-window`, `about:blank`).
3. If the browser's AppleScript URL-setting syntax differs, update `_set_front_tab_url()`.
4. Update `KNOWN_BROWSERS` in `browserbatt/config.py` if adding a new browser.
5. Smoke test: `uv run browserbatt smoke --browser <name> --workload reading --duration-seconds 90`

### Add or adjust a workload

1. Add the workload function to `browserbatt/workloads.py` (follow `daily`, `media`, `reading` patterns).
2. Register it in `WorkloadRunner.run()` dispatch.
3. Add default config to `config.example.json` and validation to `browserbatt/config.py`.
4. Add to `KNOWN_WORKLOADS` if new.
5. Update README workload docs if CLI or behavior changes.
6. Smoke test the workload.

### Change analysis or reporting

1. Update `browserbatt/analysis.py`.
2. Re-run analysis: `uv run browserbatt analyze runs/<run-id>`
3. Inspect `analysis.json` (field stability) and `report.md` (readability).
4. Note: changing aggregation logic will affect future runs; existing run directories retain their own summaries.

### Debug automation issues

1. Run `doctor` to verify prerequisites.
2. Run `smoke` with the specific browser/workload.
3. Check `runs/<id>/<browser>/<workload>/<rep>/warnings.txt` for automation hints.
4. Check `events.jsonl` for event sequence issues.
5. Safari requires: Safari → Develop → Allow Remote Automation.
6. macOS may require Accessibility permission for terminal/Python to send keystrokes.
7. BrowserController raises `RuntimeError` with user-friendly hints on accessibility failure (see `ensure_accessibility_hint()`).

### Change sampling or telemetry

1. `browserbatt/sampler.py`: Sampler class controls the sampling loop, CSV output, and warning detection.
2. `browserbatt/macos.py`: `battery_status()` and `process_snapshot()` are the raw data sources.
3. `browserbatt/util.py`: `write_csv()` for output format; `_jsonable()` for JSON serialization of dataclasses.
4. Changes to CSV column names affect `analysis.py` (which reads the CSVs) and any external tools that consume run outputs.

---

## Development Conventions

- **Dataclasses** for all configuration and data structures (import from `dataclasses` and `typing`).
- **No third-party dependencies** — use stdlib only.
- **Path objects** for all file paths; convert via `str()` only at I/O boundaries.
- **`_jsonable()`** in `util.py` handles recursive dataclass-to-dict conversion for JSON writes.
- **AppleScript** for all browser automation; fallback chains (osascript → keystroke → pkill).
- **Thread-based sampling**: Sampler runs in daemon thread; `_stop` Event for graceful shutdown.
- **JSONL events**: all events logged with `now_iso()` timestamp to `events.jsonl`.
- **Latin-square rotation**: `rotated_orders()` in config.py generates browser execution order.
- **Graceful degradation**: powermetrics optional, brightness has keyboard fallback, browser quit has osascript → pkill chain.
- Preserve all existing config keys, output column names, and JSON fields unless the user explicitly requests a migration.

---

## Git Hygiene

- Do not revert files you did not change.
- Keep `runs/` out of normal code changes; never commit generated output unless explicitly requested.
- When updating docs (README.md), keep CLI examples aligned with actual commands.
- Check `uv run python -m compileall browserbatt` before committing.