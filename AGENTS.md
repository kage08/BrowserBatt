# AI Agent Guide for BrowserBatt

BrowserBatt is a macOS browser battery-efficiency benchmark. It drives real installed browsers with the user's current profiles, extensions, cookies, and settings, then records battery, process, and optional `powermetrics` telemetry.

Use this guide when making code changes or running checks in this repository.

## Project Layout

- `browserbatt/cli.py`: command-line entry points for `doctor`, `smoke`, `run`, and `analyze`.
- `browserbatt/runner.py`: benchmark orchestration, run directories, lifecycle, and measurement flow.
- `browserbatt/browser.py`: browser app metadata and browser automation launch/control helpers.
- `browserbatt/workloads.py`: workload phase definitions and browser activity patterns.
- `browserbatt/sampler.py`: battery, process, and power telemetry sampling.
- `browserbatt/analysis.py`: aggregation, derived metrics, and report generation.
- `browserbatt/config.py`: config loading, validation, and defaults.
- `browserbatt/macos.py`: macOS-specific helpers for power, display brightness, and system tools.
- `config.example.json`: full example benchmark configuration.
- `config.quick-daily.json` and `config.quick-edge-daily.json`: shorter preset configs.
- `runs/`: generated benchmark output. Treat as local data unless the user explicitly asks to inspect or modify it.

## Tooling

- Python version: `>=3.11`.
- Package manager/runtime: `uv`.
- Package metadata lives in `pyproject.toml`.
- There are currently no third-party Python dependencies declared.

Prefer these commands:

```bash
uv run browserbatt doctor --config config.example.json
uv run browserbatt smoke --browser chrome --workload reading --duration-seconds 90
uv run browserbatt analyze runs/<run-id>
```

For module-level smoke checks, use:

```bash
uv run python -m compileall browserbatt
```

## Benchmark Safety

BrowserBatt intentionally interacts with the local machine:

- Full benchmark runs close and reopen target browsers.
- Runs use real browser profiles, including the user's logged-in sessions and extensions.
- Full runs may change display brightness to the configured value.
- Full runs start `caffeinate -dimsu` to prevent sleep.
- Battery-mode benchmark runs can take hours.
- `powermetrics` requires `sudo`; the recommended flow is `sudo -v` before a run.

Do not start long benchmark runs unless the user explicitly asks. Prefer `doctor`, `smoke`, static checks, or `analyze` while developing.

## Development Notes

- Keep changes focused; benchmark code is stateful and affects real applications.
- Preserve existing config keys and output file formats unless the user asks for a migration.
- When changing measurement or analysis logic, consider compatibility with existing `runs/<run-id>` directories.
- Avoid committing generated run outputs unless requested.
- Use structured parsing for JSON and CSV data instead of ad hoc string manipulation.
- Be careful with macOS automation behavior across browsers; Safari requires Develop -> Allow Remote Automation.

## Common Tasks

### Add or Adjust a Browser

1. Update browser metadata and launch/control behavior in `browserbatt/browser.py`.
2. Check whether workload actions in `browserbatt/workloads.py` need browser-specific handling.
3. Run a short smoke test for the browser:

```bash
uv run browserbatt smoke --browser <browser> --workload reading --duration-seconds 90
```

### Add or Adjust a Workload

1. Update workload definitions in `browserbatt/workloads.py`.
2. Update config defaults and validation in `browserbatt/config.py` if new settings are required.
3. Update README usage text when the CLI or user-facing behavior changes.
4. Run at least one short smoke test for the affected workload.

### Change Analysis or Reports

1. Update `browserbatt/analysis.py`.
2. Re-run analysis on an existing run directory when available:

```bash
uv run browserbatt analyze runs/<run-id>
```

3. Check generated `analysis.json` and `report.md` for stable field names and readable output.

## Git Hygiene

- The worktree may contain user edits. Do not revert files you did not change.
- Keep generated files in `runs/` out of normal code changes unless explicitly requested.
- If updating docs alongside code, keep examples aligned with the actual CLI in `README.md`.
