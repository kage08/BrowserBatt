from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from .macos import battery_status, process_snapshot, start_powermetrics, stop_process
from .util import write_csv


class Sampler:
    def __init__(
        self,
        out_dir: Path,
        browser: str | None,
        interval_seconds: int,
        use_powermetrics: bool,
    ) -> None:
        self.out_dir = out_dir
        self.browser = browser
        self.interval_seconds = interval_seconds
        self.use_powermetrics = use_powermetrics
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._power_rows: list[dict[str, Any]] = []
        self._process_rows: list[dict[str, Any]] = []
        self._powermetrics = None

    def start(self) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        if self.use_powermetrics:
            self._powermetrics = start_powermetrics(
                self.out_dir / "powermetrics.txt",
                max(1000, int(self.interval_seconds * 1000)),
            )
        self._thread = threading.Thread(
            target=self._loop, name="browserbatt-sampler", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.interval_seconds + 2)
        stop_process(self._powermetrics)
        self._write()

    def _loop(self) -> None:
        while not self._stop.is_set():
            status = battery_status()
            self._power_rows.append(status.__dict__)
            if self.browser:
                self._process_rows.extend(process_snapshot(self.browser))
            self._stop.wait(self.interval_seconds)

    def _write(self) -> None:
        power_fields = [
            "timestamp",
            "percent",
            "power_source",
            "is_charging",
            "voltage_mv",
            "amperage_ma",
            "instant_watts",
            "current_capacity_mah",
            "max_capacity_mah",
            "design_capacity_mah",
        ]
        write_csv(self.out_dir / "power.csv", self._power_rows, power_fields)
        proc_fields = [
            "timestamp",
            "pid",
            "ppid",
            "cpu_percent",
            "mem_percent",
            "rss_kb",
            "command",
        ]
        write_csv(self.out_dir / "processes.csv", self._process_rows, proc_fields)
        self._write_warnings()

    def _write_warnings(self) -> None:
        warnings: list[str] = []
        sources = {
            row.get("power_source")
            for row in self._power_rows
            if row.get("power_source")
        }
        if len(sources) > 1:
            warnings.append(f"Power source changed during sample: {sorted(sources)}")
        if any(row.get("is_charging") for row in self._power_rows):
            warnings.append("Battery reported charging during sample.")
        missing_watts = sum(
            1 for row in self._power_rows if row.get("instant_watts") in (None, "")
        )
        if self._power_rows and missing_watts == len(self._power_rows):
            warnings.append("No instant watt samples were available.")
        powermetrics = self.out_dir / "powermetrics.txt"
        if self.use_powermetrics and powermetrics.exists():
            text = powermetrics.read_text(encoding="utf-8", errors="replace")[
                :2000
            ].lower()
            if (
                "must be run as root" in text
                or "operation not permitted" in text
                or "a password is required" in text
            ):
                warnings.append(
                    "powermetrics did not have permission; run `sudo -v` before BrowserBatt for component power telemetry."
                )
        if warnings:
            (self.out_dir / "warnings.txt").write_text(
                "\n".join(warnings) + "\n", encoding="utf-8"
            )
