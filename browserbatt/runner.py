from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from .analysis import summarize_run
from .browser import BrowserController
from .config import BrowserBattConfig, rotated_orders
from .macos import battery_status, capture_environment, ensure_screen_brightness, prevent_sleep
from .sampler import Sampler
from .util import append_jsonl, now_iso, sleep_until, write_json
from .workloads import WorkloadRunner


class LowBatteryStop(RuntimeError):
    """Raised when battery drops below the configured minimum threshold."""


def run_workload(config: BrowserBattConfig, workload: str, out_root: Path, dry_run: bool = False) -> Path:
    if workload not in config.workloads:
        raise ValueError(f"Workload not configured: {workload}")
    run_id = datetime.now().strftime("%Y-%m-%dT%H%M%S-%f")
    root = out_root / run_id
    root.mkdir(parents=True, exist_ok=False)

    status = {"started_at": now_iso(), "completed": False, "partial": False, "error": None}
    write_json(root / "status.json", status)
    _progress(f"Run directory: {root}")
    try:
        with prevent_sleep(f"BrowserBatt {workload}") as caffeinate:
            _progress("Setting brightness and capturing environment")
            _set_brightness(config, dry_run=dry_run, context="start")
            env = capture_environment()
            env["caffeinate"] = caffeinate
            write_json(root / "metadata.json", env)
            write_json(root / "effective_config.json", config)
            _preflight(config, dry_run=dry_run, context="start")

            measurement = config.measurement
            _progress(f"Baseline start: {measurement.baseline_seconds}s")
            _baseline(root / "baseline-start", measurement.baseline_seconds, measurement, config, dry_run)

            browsers = [b for b in measurement.browser_order if b in config.browsers]
            orders = rotated_orders(browsers, measurement.repetitions)

            for browser in browsers:
                _preflight(config, dry_run=dry_run, context=f"warmup {browser}")
                _progress(f"Warmup {browser}: {measurement.warmup_seconds}s")
                _one_run(root, config, workload, browser, "warmup-01", measurement.warmup_seconds, warmup=True)
                _progress(f"Cooldown after warmup {browser}: {measurement.cooldown_seconds}s")
                _cooldown(measurement.cooldown_seconds)

            for rep_index, order in enumerate(orders, start=1):
                for browser in order:
                    _preflight(config, dry_run=dry_run, context=f"rep {rep_index} {browser}")
                    duration = int(config.workloads[workload].get("duration_seconds", 720))
                    _progress(f"Measured run {rep_index}/{measurement.repetitions} {browser}: {duration}s")
                    _one_run(
                        root,
                        config,
                        workload,
                        browser,
                        f"rep-{rep_index:02d}",
                        duration,
                        warmup=False,
                    )
                    _progress(f"Cooldown after rep {rep_index} {browser}: {measurement.cooldown_seconds}s")
                    _cooldown(measurement.cooldown_seconds)

            _progress(f"Baseline end: {measurement.baseline_seconds}s")
            _baseline(root / "baseline-end", measurement.baseline_seconds, measurement, config, dry_run)
        status["completed"] = True
        status["finished_at"] = now_iso()
        write_json(root / "status.json", status)
    except LowBatteryStop as exc:
        status["partial"] = True
        status["error"] = repr(exc)
        status["finished_at"] = now_iso()
        write_json(root / "status.json", status)
        append_jsonl(root / "events.jsonl", {"timestamp": time.time(), "event": "run_stopped_low_battery", "error": repr(exc)})
        _progress(f"Stopping early due to low battery: {exc}")
    except Exception as exc:
        status["error"] = repr(exc)
        status["finished_at"] = now_iso()
        write_json(root / "status.json", status)
        append_jsonl(root / "events.jsonl", {"timestamp": time.time(), "event": "run_error", "error": repr(exc)})
        raise
    finally:
        try:
            _write_cleanup_notes(root)
        except Exception as cleanup_exc:
            append_jsonl(root / "events.jsonl", {"timestamp": time.time(), "event": "cleanup_note_error", "error": repr(cleanup_exc)})
    return root


def estimate_runtime(config: BrowserBattConfig, workload: str) -> int:
    m = config.measurement
    browsers = [b for b in m.browser_order if b in config.browsers]
    duration = int(config.workloads[workload].get("duration_seconds", 720))
    effective_duration = _estimated_workload_seconds(workload, duration)
    run_count = len(browsers) * (1 + m.repetitions)
    browser_launch_overhead = run_count * 20
    warmups = len(browsers) * m.warmup_seconds
    measured = len(browsers) * m.repetitions * effective_duration
    cooldowns = (len(browsers) + len(browsers) * m.repetitions) * m.cooldown_seconds
    baselines = 2 * m.baseline_seconds
    return warmups + measured + cooldowns + baselines + browser_launch_overhead


def _estimated_workload_seconds(workload: str, configured_seconds: int) -> int:
    if workload == "daily":
        # Multi-tab daily runs have a fixed tab/page setup cost. For normal
        # 12-minute runs this is inside the configured duration; for tiny smoke
        # configs it dominates elapsed time.
        return max(configured_seconds, 75)
    return configured_seconds


def _one_run(
    root: Path,
    config: BrowserBattConfig,
    workload: str,
    browser: str,
    rep: str,
    duration_seconds: int,
    warmup: bool,
) -> None:
    run_dir = root / browser / workload / rep
    run_dir.mkdir(parents=True, exist_ok=True)
    append_jsonl(root / "events.jsonl", {"timestamp": time.time(), "event": "run_start", "browser": browser, "workload": workload, "rep": rep})
    controller = BrowserController(browser, config.automation.viewport_width, config.automation.viewport_height)
    sampler: Sampler | None = None
    error: str | None = None
    started_at = now_iso()
    try:
        _progress(f"Launching clean {browser} window for {rep}")
        controller.launch_clean()
        sampler = Sampler(run_dir, browser, config.measurement.sample_interval_seconds, config.measurement.use_powermetrics)
        sampler.start()
        _progress(f"Started sampling {browser} {rep}")
        if duration_seconds > 0:
            runner = WorkloadRunner(controller, run_dir / "events.jsonl", config.automation.typing_cadence_seconds)
            runner.run(workload, config.workloads[workload], duration_seconds)
        else:
            append_jsonl(run_dir / "events.jsonl", {"timestamp": time.time(), "event": "workload_skip", "reason": "zero duration"})
    except Exception as exc:
        error = repr(exc)
        append_jsonl(
            root / "events.jsonl",
            {"timestamp": time.time(), "event": "run_error", "browser": browser, "workload": workload, "rep": rep, "error": error},
        )
        append_jsonl(run_dir / "events.jsonl", {"timestamp": time.time(), "event": "run_error", "error": error})
        raise
    finally:
        cleanup_errors: list[str] = []
        if sampler:
            try:
                sampler.stop()
            except Exception as sampler_exc:
                cleanup_errors.append(f"sampler_stop: {sampler_exc!r}")
        try:
            controller.close()
        except Exception as close_exc:
            cleanup_errors.append(f"browser_close: {close_exc!r}")
            append_jsonl(run_dir / "events.jsonl", {"timestamp": time.time(), "event": "browser_close_error", "error": repr(close_exc)})
        if (run_dir / "power.csv").exists():
            try:
                summarize_run(run_dir)
            except Exception as summary_exc:
                cleanup_errors.append(f"summarize_run: {summary_exc!r}")
        if cleanup_errors:
            append_jsonl(run_dir / "events.jsonl", {"timestamp": time.time(), "event": "cleanup_errors", "errors": cleanup_errors})
        write_json(
            run_dir / "run_metadata.json",
            {
                "browser": browser,
                "workload": workload,
                "rep": rep,
                "warmup": warmup,
                "duration_seconds": duration_seconds,
                "started_at": started_at,
                "finished_at": now_iso(),
                "completed": error is None,
                "error": error,
                "cleanup_errors": cleanup_errors,
            },
        )
        append_jsonl(
            root / "events.jsonl",
            {"timestamp": time.time(), "event": "run_end", "browser": browser, "workload": workload, "rep": rep, "warmup": warmup, "completed": error is None},
        )


def _baseline(out_dir: Path, seconds: int, measurement, config: BrowserBattConfig, dry_run: bool) -> None:
    _preflight(config, dry_run=dry_run, context=f"baseline {out_dir.name}")
    sampler = Sampler(out_dir, None, measurement.sample_interval_seconds, measurement.use_powermetrics)
    sampler.start()
    try:
        sleep_until(time.monotonic() + seconds)
    finally:
        sampler.stop()
        if (out_dir / "power.csv").exists():
            summarize_run(out_dir)


def _cooldown(seconds: int) -> None:
    sleep_until(time.monotonic() + seconds)


def _preflight(config: BrowserBattConfig, dry_run: bool, context: str) -> None:
    _set_brightness(config, dry_run=dry_run, context=context)
    status = battery_status()
    if config.measurement.require_battery_power and not dry_run:
        if status.power_source and "battery" not in status.power_source.lower():
            raise RuntimeError(f"Mac is not on battery power during {context}: {status.power_source}")
        if status.is_charging:
            raise RuntimeError(f"Mac appears to be charging during {context}")
    if status.percent is not None and status.percent < config.measurement.min_battery_percent:
        raise LowBatteryStop(f"Battery is below minimum threshold during {context}: {status.percent}%")


def _set_brightness(config: BrowserBattConfig, dry_run: bool, context: str) -> None:
    target = config.measurement.screen_brightness_percent
    if target is None:
        return
    try:
        ensure_screen_brightness(target)
    except RuntimeError:
        if dry_run:
            return
        raise


def _write_cleanup_notes(root: Path) -> None:
    urls: list[str] = []
    for events in root.glob("*/**/events.jsonl"):
        for line in events.read_text(encoding="utf-8").splitlines():
            if "google_doc_created_or_opened" not in line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            url = data.get("url")
            if url and url.startswith("https://docs.google.com/document/d/") and url not in urls:
                urls.append(url)
    if not urls:
        return
    lines = [
        "# Google Docs Cleanup",
        "",
        "BrowserBatt captured these disposable Google Docs URLs during the run.",
        "Automatic deletion is not implemented because reliable deletion requires an authenticated Google Drive API integration or brittle UI automation.",
        "Delete these after verifying the benchmark data:",
        "",
    ]
    lines.extend(f"- {url}" for url in urls)
    (root / "google-docs-cleanup.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _progress(message: str) -> None:
    print(f"[{now_iso()}] {message}", flush=True)
