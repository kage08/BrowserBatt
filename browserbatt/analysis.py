from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from statistics import mean, median, stdev
from typing import Any

from .util import write_json


def summarize_run(run_dir: Path) -> dict[str, Any]:
    power_path = run_dir / "power.csv"
    rows = _read_csv(power_path)
    watts = [_float(r.get("instant_watts")) for r in rows]
    watts = [w for w in watts if w is not None and w > 0]
    percents = [_int(r.get("percent")) for r in rows]
    percents = [p for p in percents if p is not None]
    summary = {
        "sample_count": len(rows),
        "watts_mean": mean(watts) if watts else None,
        "watts_median": median(watts) if watts else None,
        "watts_min": min(watts) if watts else None,
        "watts_max": max(watts) if watts else None,
        "battery_percent_start": percents[0] if percents else None,
        "battery_percent_end": percents[-1] if percents else None,
        "battery_percent_delta": (percents[0] - percents[-1])
        if len(percents) >= 2
        else None,
    }
    write_json(run_dir / "summary.json", summary)
    return summary


def analyze(root: Path) -> dict[str, Any]:
    baseline_watts = _baseline_watts(root)
    summaries: list[dict[str, Any]] = []
    for summary_path in root.glob("*/**/summary.json"):
        rel = summary_path.relative_to(root).parts
        if len(rel) < 4:
            continue
        browser, workload, rep = rel[0], rel[1], rel[2]
        data = json.loads(summary_path.read_text(encoding="utf-8"))
        data.update({"browser": browser, "workload": workload, "rep": rep})
        summaries.append(data)

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in summaries:
        if row["rep"].startswith("warmup"):
            continue
        grouped.setdefault((row["browser"], row["workload"]), []).append(row)

    results: list[dict[str, Any]] = []
    for (browser, workload), rows in sorted(grouped.items()):
        watts = [r["watts_mean"] for r in rows if r.get("watts_mean")]
        result = {
            "browser": browser,
            "workload": workload,
            "runs": len(rows),
            "usable_runs": len(watts),
            "mean_watts": mean(watts) if watts else None,
            "median_watts": median(watts) if watts else None,
            "stdev_watts": stdev(watts) if len(watts) > 1 else None,
            "ci95_watts": _ci95(watts),
            "baseline_watts": baseline_watts,
        }
        result["incremental_watts"] = (
            result["mean_watts"] - baseline_watts
            if result["mean_watts"] is not None and baseline_watts is not None
            else None
        )
        result["estimated_battery_life_hours"] = _battery_life(
            root, result["mean_watts"]
        )
        results.append(result)

    report = {"root": str(root), "baseline_watts": baseline_watts, "results": results}
    write_json(root / "analysis.json", report)
    write_markdown_report(root, report)
    return report


def write_markdown_report(root: Path, report: dict[str, Any]) -> None:
    lines = ["# BrowserBatt Report", ""]
    lines.append(f"Run directory: `{root}`")
    lines.append("")
    lines.append(f"Baseline watts: `{_fmt(report.get('baseline_watts'))}`")
    lines.append("")
    lines.append(
        "| Workload | Browser | Runs | Usable | Mean W | Incremental W | Median W | 95% CI W | Est. Battery Hours |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in report["results"]:
        lines.append(
            "| {workload} | {browser} | {runs} | {usable} | {mean} | {incremental} | {median} | {ci} | {life} |".format(
                workload=row["workload"],
                browser=row["browser"],
                runs=row["runs"],
                usable=row["usable_runs"],
                mean=_fmt(row["mean_watts"]),
                incremental=_fmt(row["incremental_watts"]),
                median=_fmt(row["median_watts"]),
                ci=_fmt(row["ci95_watts"]),
                life=_fmt(row["estimated_battery_life_hours"]),
            )
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Power is based on macOS battery current/voltage samples when available.",
            "- `powermetrics.txt` files are retained per run when permission allowed collection.",
            "- Battery-life estimates use captured battery capacity metadata when available; otherwise they are omitted.",
            "- Warmup runs are excluded from aggregate statistics.",
        ]
    )
    (root / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _battery_life(root: Path, watts: float | None) -> float | None:
    if not watts or watts <= 0:
        return None
    meta = root / "metadata.json"
    if not meta.exists():
        return None
    data = json.loads(meta.read_text(encoding="utf-8"))
    battery = data.get("battery", {})
    max_mah = battery.get("max_capacity_mah")
    voltage_mv = battery.get("voltage_mv")
    if not max_mah or not voltage_mv:
        return None
    wh = (max_mah * voltage_mv) / 1_000_000.0
    return wh / watts


def _baseline_watts(root: Path) -> float | None:
    values = []
    for path in [
        root / "baseline-start" / "summary.json",
        root / "baseline-end" / "summary.json",
    ]:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            value = data.get("watts_mean")
            if value:
                values.append(value)
    return mean(values) if values else None


def _ci95(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    return 1.96 * stdev(values) / math.sqrt(len(values))


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)
