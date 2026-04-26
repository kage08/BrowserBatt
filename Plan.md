# BrowserBatt Plan

## Goal

Build a macOS benchmark suite that estimates the relative battery efficiency of installed browsers under realistic, repeatable browsing workloads.

Initial browsers:

- Google Chrome
- Safari
- Microsoft Edge
- Firefox

Primary outputs:

- Average system power draw while each browser runs each workload
- Browser-attributable power estimate where macOS exposes enough process-level data
- Estimated battery life under each workload
- Confidence intervals / variability across repeated runs
- A ranked comparison with caveats clearly stated
- Separate reports per workload, so each workload can be measured and interpreted independently

Correctness and robustness are the top priorities. The benchmark should standardize everything except the browser's existing user configuration, including extensions, logged-in state, settings, hardware acceleration preferences, content blocking, and other real profile differences.

## Confirmed Decisions

- Use the user's real installed browsers as configured today.
- Use existing browser profiles, cookies, logged-in state, extensions, settings, and content blockers.
- Start every benchmark run from a clean browser window with zero open tabs.
- Use live websites only for the benchmark workloads.
- Measure each workload separately.
- Budget up to 6 hours per workload across all browsers.
- Create a disposable Google Doc for the benchmark and delete it after the benchmark finishes.
- Measure YouTube with the user's normal account/profile/extensions exactly as-is.
- Use both battery discharge telemetry and `powermetrics` where available; report whichever signals are most accurate and clearly label their limitations.
- Include Safari; the user is comfortable enabling Safari's "Allow Remote Automation" if needed.
- Do not include clean-profile comparisons in the initial implementation.

## Design Principles

1. Use each browser's existing profile/configuration.
2. Start each run from a clean browser window with zero existing tabs.
3. Do not permanently modify browser profiles.
4. Standardize workload timing, page order, interaction cadence, viewport size, network conditions where feasible, screen brightness, power settings, and sampling method.
5. Run multiple repetitions and randomize or rotate browser order to reduce thermal, battery, and background-task bias.
6. Measure both idle baseline and workload power so results can report:
   - total system draw during browsing
   - incremental draw over baseline
   - estimated battery life from total draw
7. Prefer OS-level measurements over JavaScript/browser-internal metrics for power.
8. Avoid relying on one metric. Combine battery discharge, `powermetrics`, process CPU/GPU observations, and run metadata.

## Important Constraints

### Browser Profiles

Use the user's existing browser profiles to preserve real-world settings and extensions.

Risk: automation may disturb sessions, restore windows, or leave tabs open.

Mitigation:

- Before each run, close target browser cleanly.
- Launch a fresh window.
- Ensure no tabs from prior sessions are present.
- After each run, close only windows created by the benchmark when possible.
- Save run logs so unexpected restore/session behavior is visible.

### Safari Automation

Safari automation on macOS can require enabling:

- Develop menu
- "Allow Remote Automation"

Safari is also less uniform than Chromium browsers for WebDriver automation. The benchmark should support Safari, but implementation needs a Safari-specific launch/control path.

### Google Docs

A realistic "editing Google Docs" workload requires authentication and may touch real account state.

Confirmed approach:

- Create a disposable benchmark Google Doc.
- Use the user's normal logged-in browser profile to access it.
- Type into the document during each run with deterministic content and human-like cadence.
- Prefer creating a fresh document or clean document copy per browser/workload run if automation can do that reliably.
- Delete the benchmark document(s) after the benchmark completes.
- Log document creation/deletion IDs or URLs so cleanup is auditable.

Fallback only if Docs creation/deletion automation is unreliable:

- Create one disposable benchmark document before the run.
- Clear/reset the document between repetitions.
- Delete it after the run.

### YouTube

YouTube is dynamic and may vary ads, codecs, recommendations, AB experiments, network conditions, and account state.

Confirmed approach:

- Use the user's normal YouTube/account/browser state exactly as configured.
- Do not disable extensions, ad blockers, login state, cookies, or account personalization.
- Treat those profile differences as part of the real-world browser configuration being measured.

Mitigations:

- Use a fixed video URL.
- Prefer a known public video with stable availability.
- Force a target resolution where possible.
- Let playback warm up before measurement.
- Record actual playback resolution / dropped frames if possible.
- Use the same account/profile state per browser, accepting that extensions and login state are part of the real-world config.

### News/Substack/GitHub Pages

Live websites change. For realism, that is acceptable, but robust comparisons need repeatability.

Confirmed approach:

- Use live websites only in the initial benchmark.
- Use fixed URLs for each phase.
- Record final resolved URLs, titles, HTTP/navigation failures, and timestamps.
- Keep page choices stable across browsers and repetitions.

This benchmark answers "what happens for this user's configured browsers on the live web during this measurement period?"

## Measurement Strategy

### Primary Metric

Use wall-power/battery discharge derived from macOS battery telemetry and/or system power reporting:

- `pmset -g batt` for battery percentage and charging/discharging status
- `ioreg` battery fields for current, voltage, capacity, and cycle-related data where available
- `powermetrics` for package/CPU/GPU/ANE/display-related power samples where supported

Measurement priority:

1. Average system watts over the workload duration from battery current/voltage or reliable macOS power telemetry.
2. `powermetrics` package/component power samples, used for corroboration and phase/process diagnostics.
3. Battery percentage drop normalized by battery capacity, used only as a fallback or long-run sanity check.

Report both:

- total average system watts
- incremental watts over nearby idle baseline
- estimated battery life from total average watts
- signal quality/availability for each metric

Important: short runs based only on battery percentage are noisy. Power sampling plus repeated 10-30 minute runs is preferable.

### Baseline Measurement

Before browser runs, measure idle system power:

- Same brightness
- Same power source state: battery only, not charging
- Same Wi-Fi
- No target browser running
- Benchmark controller running
- Same display awake state
- Same sampling cadence

Recommended:

- 5-10 minute idle baseline at beginning
- 5-10 minute idle baseline at end
- Optionally another baseline between browser groups

Report both:

- total average watts while browsing
- incremental watts = browsing watts - nearby idle baseline watts

### Battery-Life Estimate

For each browser/workload:

```text
estimated_battery_life_hours = usable_battery_energy_wh / average_total_power_w
```

Battery energy source:

- Prefer current full-charge capacity converted to Wh if available.
- Otherwise use user-provided Mac battery capacity or an Apple model lookup.

Report assumptions:

- estimated full-charge energy
- battery health/capacity used
- screen brightness
- workload duration
- confidence interval

### Sampling Cadence

Recommended:

- Collect power samples every 1-5 seconds.
- Collect browser/process CPU/memory samples every 1-5 seconds.
- Mark workload phases with timestamps.
- Save raw logs as CSV/JSONL.

### Repetitions

The user allows up to 6 hours per workload across all browsers.

Recommended final protocol per workload:

- 4 browsers
- 1 warm-up run per browser, excluded from final stats
- 5 measured repetitions per browser
- 12 minute measured duration per repetition
- 3 minute cooldown/settling interval between measured runs
- 5-10 minute baseline at the beginning and end of each workload

Approximate per-workload runtime:

```text
warmups:      4 browsers * 6-8 min ~= 24-32 min
measurements: 4 browsers * 5 reps * 12 min = 240 min
cooldowns:    about 20 intervals * 3 min = 60 min
baselines:    2 * 5-10 min = 10-20 min
total:        about 5.6-5.9 hours depending on warmup/baseline settings
```

If longer per-run measurements are preferred later, use:

- 1 warm-up run per browser, excluded
- 4 measured repetitions per browser
- 16-18 minute measured duration per repetition

Default implementation target:

- Use 5 measured repetitions by default.
- Automatically estimate total runtime before starting.
- Ask for confirmation if the selected configuration exceeds 6 hours for a workload.
- Browser order rotated using a Latin-square style order.

Example order for 4 browsers and 5 repetitions:

1. Chrome, Safari, Edge, Firefox
2. Safari, Edge, Firefox, Chrome
3. Edge, Firefox, Chrome, Safari
4. Firefox, Chrome, Safari, Edge
5. Chrome, Edge, Safari, Firefox

## Environment Standardization

Before every run:

- Confirm Mac is on battery, not plugged in.
- Confirm battery is within a chosen range, ideally 80%-30%.
- Confirm Low Power Mode setting is fixed.
- Confirm screen brightness is fixed.
- Confirm keyboard backlight is fixed/off.
- Confirm display resolution and refresh rate are fixed.
- Confirm True Tone, Night Shift, auto brightness, and automatic graphics switching settings are recorded.
- Confirm Wi-Fi network is the same.
- Confirm no OS update, backup, indexing, or heavy background task is active.
- Confirm target browser is closed.
- Close unrelated browser windows where possible.
- Record ambient run metadata:
  - macOS version
  - machine model
  - CPU/GPU
  - memory
  - battery health/capacity
  - browser versions
  - connected external displays
  - power mode
  - display brightness
  - thermal state if available

During runs:

- Prevent sleep.
- Keep display awake.
- Avoid user input.
- Do not switch apps manually.
- Log any interruption.

After each run:

- Close target browser.
- Wait for a cooldown/settling interval.
- Record battery state and thermal state.

## Workloads

### Workload A: Daily Work Flow

Purpose: approximate a realistic mixed browsing session.

Suggested measured duration: 12 minutes per run by default, or 16-18 minutes for shorter repetition counts.

Phases:

1. Start browser with clean window
2. YouTube playback
   - Open fixed YouTube video
   - Wait for page load
   - Start playback
   - Set stable quality if possible
   - Watch for 5-8 minutes
   - Periodically move mouse or scroll page lightly
3. Google Docs editing
   - Open benchmark document
   - Type text at human-like cadence
   - Use selection, formatting, undo/redo, comments or headings if desired
   - Continue for 5-8 minutes
4. News reading
   - Open a fixed news article or front page
   - Scroll slowly
   - Open one or two links
   - Spend 3-5 minutes
5. Substack/blog reading
   - Open fixed Substack/blog article
   - Scroll, pause, select text, maybe open comments
   - Spend 3-5 minutes
6. GitHub repo browsing
   - Open fixed repository
   - Navigate README, file tree, source files, issues or PRs
   - Search within page/repo if practical
   - Spend 4-6 minutes
7. Close browser

Behavior should be scripted with realistic delays and interactions:

- scrolls with pauses
- typed text with variable intervals
- link clicks rather than direct URL jumps where practical
- waits for network idle or DOM readiness
- deterministic phase durations

### Workload B: Media-Heavy Browsing

Purpose: isolate video playback, compositing, hardware decode, and background-tab behavior.

Suggested measured duration: 12 minutes per run by default, or 16-18 minutes for shorter repetition counts.

Phases:

1. Start clean browser window
2. Open YouTube fixed video
3. Verify playback starts
4. Set target quality
5. Play for the configured measured duration
6. Optional: switch to a second tab with a live article for 2-3 minutes while video continues picture-in-tab/background behavior, if this matches user interest
7. Close browser

Metrics to capture if possible:

- video resolution
- codec
- dropped frames
- tab visibility
- whether playback was foreground or background

### Workload C: Live Reading/Code Browsing

Purpose: measure browsing efficiency for mostly text/code-heavy live web usage without video or document editing.

Suggested measured duration: 12 minutes per run by default, or 16-18 minutes for shorter repetition counts.

Phases:

1. Start browser with clean window
2. News reading
   - Open fixed news article/front page
   - Scroll slowly
   - Open one or two same-site links
3. Substack/blog reading
   - Open fixed article
   - Scroll, pause, select text, optionally open comments
4. GitHub repo browsing
   - Open fixed repository
   - Navigate README, file tree, source files, issues or PRs
   - Use find/search where practical
5. Close browser

This workload intentionally uses live websites, not local replay.

## Automation Approach

### Candidate Stack

Use Playwright where possible:

- Chromium/Chrome channel for Google Chrome
- Chromium/Edge channel for Microsoft Edge
- Firefox where Playwright can launch system Firefox or bundled Firefox depending on feasibility
- Safari via WebKit is not the same as installed Safari, so for true Safari use Safari WebDriver / AppleScript as needed

Because the benchmark must test installed browsers with existing profiles, implementation may need browser-specific launch adapters:

- Chrome: launch installed app with remote debugging port and existing user data dir, or attach via AppleScript/Chrome DevTools Protocol.
- Edge: same Chromium strategy with Edge paths.
- Firefox: Marionette/WebDriver or Playwright if it can target installed Firefox with the existing profile safely.
- Safari: `safaridriver` plus AppleScript/WebDriver, requiring user-enabled automation permissions.

The plan should explicitly validate that each adapter is using the real installed browser and the intended profile.

### Clean Window Guarantee

For each browser:

1. Record currently running state.
2. Ask target browser to quit.
3. Wait until process exits.
4. Launch browser.
5. Close any restored windows/tabs.
6. Open exactly one new window.
7. Verify tab count is zero/blank start page before benchmark URL.
8. Start workload timer only after this state is achieved.

If a browser's restore behavior cannot be suppressed without changing user settings, the runner should close restored tabs/windows at the beginning and log that it did so.

## Data Layout

Suggested output directory:

```text
runs/
  2026-04-25T013000/
    metadata.json
    config.json
    baseline-start/
      power.csv
      processes.csv
    chrome/
      daily-workflow/
        rep-01/
          metadata.json
          events.jsonl
          power.csv
          processes.csv
          summary.json
    safari/
    edge/
    firefox/
    baseline-end/
    report.md
    report.html
```

## Analysis

For each browser/workload:

- Remove warm-up run if configured.
- Compute mean watts per run.
- Compute median watts per run.
- Compute standard deviation.
- Compute 95% confidence interval, preferably via bootstrap if sample size is small.
- Compute incremental power over nearest baseline.
- Compute estimated battery life from total watts.
- Flag outlier runs rather than silently dropping them.
- Include phase-level breakdown if event timestamps align with power samples.

Report should include:

- ranking table
- per-workload charts
- per-phase charts
- raw run table
- environment summary
- caveats
- reproducibility checklist

## Robustness Checks

The runner should fail or warn if:

- Mac is plugged in when battery testing is required.
- Battery is below a configured minimum.
- Battery is above/below configured range.
- Screen brightness cannot be read or controlled.
- Browser version cannot be detected.
- Browser starts with unexpected existing tabs that cannot be closed.
- Workload page fails to load.
- YouTube playback is not detected.
- Google Docs document is unavailable.
- Power sampling fails.
- Thermal pressure is high.
- CPU usage from unrelated processes exceeds a threshold during baseline or run.
- Network connectivity changes.

## Implementation Milestones

1. Create project scaffold
   - CLI runner
   - config file
   - browser registry
   - output directory structure

2. Implement environment capture
   - macOS version and hardware
   - battery info
   - power settings
   - display info
   - browser versions

3. Implement power sampler
   - battery/power telemetry
   - process sampler
   - timestamped CSV/JSONL output

4. Implement browser lifecycle adapters
   - Chrome
   - Edge
   - Firefox
   - Safari

5. Implement workload scripting
   - daily workflow
   - media-heavy workflow
   - live reading/code-browsing workflow

6. Implement run scheduler
   - repetitions
   - randomized/rotated order
   - warm-up handling
   - cooldown intervals

7. Implement analysis/reporting
   - summary stats
   - confidence intervals
   - battery-life estimates
   - charts
   - Markdown/HTML report

8. Validate with dry runs
   - short 1-minute smoke test per browser
   - confirm clean windows
   - confirm logs
   - confirm pages/interactions

9. Run full benchmark
   - collect data
   - inspect outliers
   - produce final report

## Remaining Implementation Questions

These are no longer policy questions; they are configuration values the implementation should make easy to edit.

- Which exact YouTube URL should be used?
- Which exact news URLs should be used?
- Which exact Substack/blog URLs should be used?
- Which exact GitHub repository should be used?
- Should each workload run immediately end-to-end, or should the runner support pausing between browser groups?
- What minimum battery percentage should stop a run? Proposed default: stop below 25%.
- What battery range should final measurements target? Proposed default: start at 90%-80% and stop no lower than 25%-30%.
- What fixed screen brightness value should be used? Final default: set and verify main display brightness at 50%.
- Should cleanup delete Google Docs immediately after each run or at the end of the workload? Proposed default: delete at the end, with a cleanup command that can be retried.

## Final Default Choices

- Existing browser profiles/configs only.
- Live websites only.
- Separate workload runs and separate workload reports.
- Workloads:
  - daily workflow
  - media-heavy YouTube workflow
  - live reading/code-browsing workflow
- Up to 6 hours per workload across all browsers.
- Prefer 5 measured repetitions per browser where feasible.
- Use 1 warm-up run per browser per workload, excluded from stats.
- Use `powermetrics` plus battery telemetry where available.
- Use disposable Google Docs and delete them after measurement.
- Produce both Markdown and HTML reports.
