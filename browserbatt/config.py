from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

KNOWN_BROWSERS = ("chrome", "safari", "edge", "firefox", "zen")
KNOWN_WORKLOADS = ("daily", "media", "reading")


@dataclass
class MeasurementConfig:
    repetitions: int = 5
    warmup_seconds: int = 360
    cooldown_seconds: int = 180
    baseline_seconds: int = 600
    sample_interval_seconds: int = 2
    min_battery_percent: int = 15
    require_battery_power: bool = True
    use_powermetrics: bool = True
    screen_brightness_percent: int | None = 50
    browser_order: list[str] = field(default_factory=lambda: list(KNOWN_BROWSERS))


@dataclass
class AutomationConfig:
    viewport_width: int = 1440
    viewport_height: int = 900
    typing_cadence_seconds: float = 0.04
    docs_cleanup_policy: str = "record_for_manual_cleanup"


@dataclass
class BrowserBattConfig:
    browsers: list[str]
    workloads: dict[str, dict[str, Any]]
    measurement: MeasurementConfig
    automation: AutomationConfig


def load_config(path: Path) -> BrowserBattConfig:
    raw = json.loads(path.read_text(encoding="utf-8"))
    measurement = MeasurementConfig(**raw.get("measurement", {}))
    automation = AutomationConfig(**raw.get("automation", {}))
    browsers = raw.get("browsers", list(KNOWN_BROWSERS))
    for browser in browsers:
        if browser not in KNOWN_BROWSERS:
            raise ValueError(f"Unknown browser: {browser}")
    config = BrowserBattConfig(
        browsers=browsers,
        workloads=raw.get("workloads", {}),
        measurement=measurement,
        automation=automation,
    )
    _validate(config)
    return config


def rotated_orders(browsers: list[str], repetitions: int) -> list[list[str]]:
    if not browsers:
        return []
    return [
        browsers[i % len(browsers) :] + browsers[: i % len(browsers)]
        for i in range(repetitions)
    ]


def _validate(config: BrowserBattConfig) -> None:
    if not config.browsers:
        raise ValueError("At least one browser must be configured.")
    m = config.measurement
    if m.repetitions < 1:
        raise ValueError("measurement.repetitions must be >= 1.")
    if m.sample_interval_seconds < 1:
        raise ValueError("measurement.sample_interval_seconds must be >= 1.")
    for field_name in [
        "warmup_seconds",
        "cooldown_seconds",
        "baseline_seconds",
        "min_battery_percent",
    ]:
        if getattr(m, field_name) < 0:
            raise ValueError(f"measurement.{field_name} must be >= 0.")
    if (
        m.screen_brightness_percent is not None
        and not 0 <= m.screen_brightness_percent <= 100
    ):
        raise ValueError(
            "measurement.screen_brightness_percent must be between 0 and 100, or null."
        )
    for browser in m.browser_order:
        if browser not in KNOWN_BROWSERS:
            raise ValueError(f"Unknown browser in measurement.browser_order: {browser}")
    if not any(browser in config.browsers for browser in m.browser_order):
        raise ValueError(
            "measurement.browser_order must include at least one configured browser."
        )
