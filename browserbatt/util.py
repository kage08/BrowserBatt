from __future__ import annotations

import csv
import json
import subprocess
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterable


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def run_cmd(
    args: list[str], timeout: float | None = None, check: bool = False
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, text=True, capture_output=True, timeout=timeout, check=check
    )


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(_jsonable(data), f, indent=2, sort_keys=True)
        f.write("\n")


def append_jsonl(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(_jsonable(data), sort_keys=True))
        f.write("\n")


def write_csv(
    path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _jsonable(data: Any) -> Any:
    if is_dataclass(data):
        return asdict(data)
    if isinstance(data, Path):
        return str(data)
    if isinstance(data, dict):
        return {str(k): _jsonable(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_jsonable(v) for v in data]
    return data


def sleep_until(deadline_monotonic: float, tick: float = 0.25) -> None:
    while True:
        remaining = deadline_monotonic - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(tick, remaining))
