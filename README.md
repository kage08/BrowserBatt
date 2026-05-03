# BrowserBatt

BrowserBatt is a macOS battery-efficiency benchmark for real installed browsers using the user's existing profiles, extensions, cookies, and settings.

It is designed for careful long-running measurements, not quick synthetic scores.

## Quick Start

```bash
uv run browserbatt doctor
uv run browserbatt smoke --browser chrome --workload reading --duration-seconds 90
uv run browserbatt run --workload media --config config.example.json --yes
uv run browserbatt run --workload daily --browser edge --config config.example.json --yes
uv run browserbatt analyze runs/<run-id>
```

For richer telemetry, authenticate `sudo` before starting so BrowserBatt can launch only the `powermetrics` subprocess with cached permission while keeping browser automation under your normal user:

```bash
sudo -v
uv run browserbatt run --workload daily --config config.example.json --yes
```

The benchmark requires battery power for real measurement runs. Smoke runs can be short and are meant to validate automation.

## Recommended Run Flow

1. Edit [config.example.json](./config.example.json) if you want different URLs, repetitions, timing, browser order, or brightness.
2. Run `uv run browserbatt doctor`.
3. Enable Safari automation if Safari is included: Safari -> Develop -> Allow Remote Automation.
4. Grant Accessibility permission to the terminal/app running BrowserBatt if macOS prompts.
5. Run a short smoke test for each browser you care about.
6. Unplug the laptop.
7. Run `sudo -v` if you want `powermetrics` component telemetry.
8. Run one workload at a time with `uv run browserbatt run --workload <name> --yes`.
9. Review `runs/<run-id>/report.md`, `analysis.json`, warnings, and raw CSV files.

## Workloads

### `daily`

Mixed realistic browser work. This is the closest workload to a normal work session.

This workload is multi-tab. It starts from one clean browser window, opens the configured sites into separate tabs, keeps those tabs open, and switches between them during the run.

Phases:

- Tab 1: YouTube playback using the configured `youtube_url`.
- Tab 2: Google Docs editing using `google_docs_url`, defaulting to a new document URL.
- Tabs 3-4: news reading using up to two configured `news_urls`.
- Next tabs: blog/Substack-style reading using up to two configured `blog_urls`.
- Final tab: GitHub repository browsing using `github_url`.

The workload switches back to each tab for its phase. Earlier tabs remain open, so background tab memory, media, and extension behavior are included in the measurement.

The phase split is approximately:

- 30% YouTube
- 25% Google Docs
- 15% news
- 15% blog
- 15% GitHub

### `media`

YouTube-focused playback workload.

Behavior:

- Opens the configured `youtube_url`.
- Starts/continues playback with the YouTube `k` shortcut.
- Keeps the page active with occasional light scrolling.
- Measures browser/system power during the configured duration.

Use this workload to compare video playback, decode, compositing, and media-page behavior.

### `reading`

Live text/code browsing workload without video or Docs.

Phases:

- News reading using configured `news_urls`.
- Blog/Substack-style reading using configured `blog_urls`.
- GitHub repository browsing using `github_url`.

The phase split is approximately:

- 35% news
- 30% blog
- 35% GitHub

Use this workload to compare mostly static/live web reading and code browsing.

## CLI Reference

### `doctor`

Checks local prerequisites and prints current environment signals.

```bash
uv run browserbatt doctor --config config.example.json
```

Options:

- `--config PATH`: config file to load. Default: `config.example.json`.

Reports:

- Battery state and power source.
- Current screen brightness.
- Installed browser versions.
- Browser app availability.
- macOS tool availability: `pmset`, `ioreg`, `osascript`, `caffeinate`, `powermetrics`, `safaridriver`.

### `smoke`

Runs a short automation test. This still closes/opens the selected real browser, but it does not require battery power.

```bash
uv run browserbatt smoke --browser chrome --workload reading --duration-seconds 90
```

Options:

- `--config PATH`: config file to load. Default: `config.example.json`.
- `--browser {chrome,edge,firefox,safari,zen}`: browser to test.
- `--workload {daily,media,reading}`: workload to test. Default: `reading`.
- `--duration-seconds N`: measured workload duration for the smoke run. Default: `90`.
- `--out PATH`: output directory. Default: `runs`.

### `run`

Runs one full workload across the configured browsers.

```bash
uv run browserbatt run --workload media --config config.example.json --yes
```

Options:

- `--config PATH`: config file to load. Default: `config.example.json`.
- `--workload {daily,media,reading}`: workload to run.
- `--browser {chrome,edge,firefox,safari,zen}`: restrict the run to one browser. Repeat for a subset.
- `--out PATH`: output directory. Default: `runs`.
- `--yes`: required confirmation for a long run that closes/opens browsers.

Real benchmark runs:

- Require battery power when `require_battery_power` is true.
- Refuse to start below `min_battery_percent`.
- Stop early if battery drops below `min_battery_percent`, then generate the best partial report from completed measurements.
- Set and verify `screen_brightness_percent`, 50% by default.
- Start `caffeinate -dimsu` to prevent sleep.
- Write raw telemetry and summaries under `runs/<run-id>/`.

### `analyze`

Recomputes analysis/report files for an existing run directory.

```bash
uv run browserbatt analyze runs/<run-id>
```

Outputs:

- `analysis.json`
- `report.md`

## Configuration

Most benchmark behavior is controlled by [config.example.json](./config.example.json).

Important fields:

- `browsers`: browsers included in the run.
- `workloads.<name>.duration_seconds`: measured duration for each repetition.
- `workloads.<name>.*_url(s)`: live URLs used by workload phases.
- `measurement.repetitions`: measured repetitions per browser.
- `measurement.warmup_seconds`: warmup duration per browser, excluded from stats.
- `measurement.cooldown_seconds`: settling interval between runs.
- `measurement.baseline_seconds`: idle baseline duration at start and end.
- `measurement.sample_interval_seconds`: battery/process sampling cadence.
- `measurement.min_battery_percent`: stop threshold.
- `measurement.require_battery_power`: require unplugged battery power for full runs.
- `measurement.use_powermetrics`: attempt component telemetry with `powermetrics`.
- `measurement.screen_brightness_percent`: target brightness, 50 by default.
- `measurement.browser_order`: base browser order used for rotated repetitions.
- `automation.viewport_width` / `automation.viewport_height`: browser window size.

Default full workload timing is roughly 7.5 hours per workload across five browsers.

## Outputs

Each run creates a timestamped directory under `runs/`.

Important files:

- `metadata.json`: captured macOS, battery, browser, brightness, and environment metadata.
- `effective_config.json`: exact config used for the run.
- `events.jsonl`: top-level run events.
- `status.json`: run completion/error state.
- `baseline-start/` and `baseline-end/`: idle baseline telemetry.
- `<browser>/<workload>/<rep>/power.csv`: battery/power samples.
- `<browser>/<workload>/<rep>/processes.csv`: browser process samples.
- `<browser>/<workload>/<rep>/powermetrics.txt`: component telemetry when available.
- `<browser>/<workload>/<rep>/summary.json`: per-run summary.
- `<browser>/<workload>/<rep>/warnings.txt`: run-specific warnings, if any.
- `analysis.json`: aggregate analysis.
- `report.md`: human-readable report.
- `google-docs-cleanup.md`: captured disposable Docs URLs, if any.

## Safety Notes

- The benchmark uses your real browser profiles as configured today.
- It closes the target browser before each run to guarantee a clean window.
- It starts `caffeinate -dimsu` during runs to prevent system, display, idle, and disk sleep.
- It sets the main display brightness to the configured value, 50% by default, and real benchmark runs fail if that cannot be verified.
- It does not intentionally change browser settings.
- Google Docs support creates disposable benchmark documents when configured, then records cleanup instructions/URLs.
- Safari may require Develop -> Allow Remote Automation.
- macOS may require Accessibility permission for Terminal/Codex/Python to send keystrokes.
- Automatic Google Docs deletion is intentionally not done yet; run outputs include `google-docs-cleanup.md` with captured URLs to delete after verification.

## Files

- [Plan.md](./Plan.md): detailed benchmark plan.
- [config.example.json](./config.example.json): editable benchmark configuration.
- `browserbatt/`: CLI and implementation.
