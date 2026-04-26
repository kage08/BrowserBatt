from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .analysis import analyze
from .browser import BROWSERS, BrowserController, ensure_accessibility_hint
from .config import KNOWN_WORKLOADS, load_config
from .macos import battery_status, browser_versions, command_exists, get_screen_brightness
from .runner import estimate_runtime, run_workload


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="browserbatt")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_doctor = sub.add_parser("doctor", help="Check local macOS/browser prerequisites")
    p_doctor.add_argument("--config", type=Path, default=Path("config.example.json"))

    p_smoke = sub.add_parser("smoke", help="Run a short automation smoke test")
    p_smoke.add_argument("--config", type=Path, default=Path("config.example.json"))
    p_smoke.add_argument("--browser", choices=sorted(BROWSERS), required=True)
    p_smoke.add_argument("--workload", choices=KNOWN_WORKLOADS, default="reading")
    p_smoke.add_argument("--duration-seconds", type=int, default=90)
    p_smoke.add_argument("--out", type=Path, default=Path("runs"))

    p_run = sub.add_parser("run", help="Run one workload benchmark")
    p_run.add_argument("--config", type=Path, default=Path("config.example.json"))
    p_run.add_argument("--workload", choices=KNOWN_WORKLOADS, required=True)
    p_run.add_argument(
        "--browser",
        choices=sorted(BROWSERS),
        action="append",
        help="Only run the selected browser. Repeat to run a subset, e.g. --browser chrome --browser safari.",
    )
    p_run.add_argument("--out", type=Path, default=Path("runs"))
    p_run.add_argument("--yes", action="store_true", help="Confirm starting the long benchmark")

    p_analyze = sub.add_parser("analyze", help="Analyze a run directory")
    p_analyze.add_argument("run_dir", type=Path)

    args = parser.parse_args(argv)
    if args.cmd == "doctor":
        doctor(args.config)
    elif args.cmd == "smoke":
        smoke(args)
    elif args.cmd == "run":
        run(args)
    elif args.cmd == "analyze":
        report = analyze(args.run_dir)
        print(f"Wrote {args.run_dir / 'analysis.json'} and {args.run_dir / 'report.md'}")
        print(f"Result rows: {len(report['results'])}")


def doctor(config_path: Path) -> None:
    config = load_config(config_path)
    print("BrowserBatt doctor")
    print(f"Config: {config_path}")
    print(f"Battery: {battery_status()}")
    print(f"Screen brightness: {get_screen_brightness()}")
    print(f"Browser versions: {browser_versions()}")
    for browser in config.browsers:
        controller = BrowserController(browser, config.automation.viewport_width, config.automation.viewport_height)
        print(f"{browser}: {'installed' if controller.installed() else 'missing'} at {BROWSERS[browser].bundle_path}")
    for cmd in ["pmset", "ioreg", "osascript", "caffeinate", "powermetrics", "safaridriver"]:
        print(f"{cmd}: {'ok' if command_exists(cmd) else 'missing'}")
    print(ensure_accessibility_hint())


def smoke(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    if args.browser not in config.browsers:
        config.browsers.append(args.browser)
    config.measurement.browser_order = [args.browser]
    config.measurement.repetitions = 1
    config.measurement.warmup_seconds = 0
    config.measurement.cooldown_seconds = 0
    config.measurement.baseline_seconds = 5
    config.measurement.require_battery_power = False
    config.workloads[args.workload]["duration_seconds"] = args.duration_seconds
    root = run_workload(config, args.workload, args.out, dry_run=True)
    analyze(root)
    print(f"Smoke run complete: {root}")
    print(f"Report: {root / 'report.md'}")


def run(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    if args.browser:
        requested = list(dict.fromkeys(args.browser))
        config.browsers = requested
        config.measurement.browser_order = requested
    seconds = estimate_runtime(config, args.workload)
    hours = seconds / 3600
    print(f"Browsers: {', '.join(config.measurement.browser_order)}")
    print(f"Estimated runtime for workload '{args.workload}': {hours:.2f} hours")
    if not args.yes:
        print("Full benchmark runs close/open real browser windows and can run for hours. Re-run with --yes to start.")
        sys.exit(2)
    if hours > 6:
        print("Warning: this exceeds the 6 hour target. Reduce durations/repetitions if that is not intended.")
    root = run_workload(config, args.workload, args.out, dry_run=False)
    analyze(root)
    print(f"Benchmark complete: {root}")
    print(f"Report: {root / 'report.md'}")


if __name__ == "__main__":
    main()
