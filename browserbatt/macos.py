from __future__ import annotations

import ctypes
import os
import plistlib
import re
import shutil
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .util import run_cmd


@dataclass
class BatteryStatus:
    timestamp: float
    percent: int | None
    power_source: str | None
    is_charging: bool | None
    voltage_mv: int | None
    amperage_ma: int | None
    instant_watts: float | None
    current_capacity_mah: int | None
    max_capacity_mah: int | None
    design_capacity_mah: int | None


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


@contextmanager
def prevent_sleep(reason: str):
    proc: subprocess.Popen[str] | None = None
    if command_exists("caffeinate"):
        proc = subprocess.Popen(
            ["caffeinate", "-dimsu", "-w", str(_current_pid())],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    try:
        yield {
            "enabled": proc is not None,
            "pid": proc.pid if proc else None,
            "reason": reason,
        }
    finally:
        stop_process(proc, timeout=2)


def capture_environment() -> dict[str, Any]:
    env: dict[str, Any] = {"timestamp": time.time()}
    env["sw_vers"] = _cmd_lines(["sw_vers"])
    env["hardware"] = _cmd_lines(["system_profiler", "SPHardwareDataType"])
    env["power_settings"] = _cmd_lines(["pmset", "-g"])
    env["displays"] = _cmd_lines(["system_profiler", "SPDisplaysDataType"])
    env["thermal"] = _cmd_lines(["pmset", "-g", "therm"])
    env["battery"] = battery_status().__dict__
    env["screen_brightness"] = get_screen_brightness()
    env["browser_versions"] = browser_versions()
    return env


def get_screen_brightness() -> dict[str, Any]:
    api = _display_api()
    if api is None:
        return {"available": False, "method": None, "value": None}
    core_graphics, display_services = api
    display_id = core_graphics.CGMainDisplayID()
    value = ctypes.c_float()
    result = display_services.DisplayServicesGetBrightness(
        display_id, ctypes.byref(value)
    )
    if result != 0:
        return {
            "available": False,
            "method": "DisplayServicesGetBrightness",
            "value": None,
            "result": int(result),
        }
    return {
        "available": True,
        "method": "DisplayServicesGetBrightness",
        "value": float(value.value),
    }


def set_screen_brightness(percent: int) -> dict[str, Any]:
    target = max(0.0, min(1.0, percent / 100.0))
    api = _display_api()
    if api is not None:
        core_graphics, display_services = api
        display_id = core_graphics.CGMainDisplayID()
        result = display_services.DisplayServicesSetBrightness(
            display_id, ctypes.c_float(target)
        )
        observed = get_screen_brightness()
        return {
            "requested_percent": percent,
            "method": "DisplayServicesSetBrightness",
            "success": result == 0,
            "result": int(result),
            "observed": observed,
        }
    _set_brightness_with_keys(percent)
    observed = get_screen_brightness()
    return {
        "requested_percent": percent,
        "method": "keyboard_brightness_keys",
        "success": False,
        "result": None,
        "observed": observed,
        "warning": "Used keyboard fallback; exact brightness could not be verified.",
    }


def ensure_screen_brightness(
    percent: int, tolerance_percent: float = 2.0
) -> dict[str, Any]:
    result = set_screen_brightness(percent)
    observed = result.get("observed", {})
    value = observed.get("value")
    if value is None:
        raise RuntimeError(
            f"Could not verify screen brightness after setting {percent}%: {result}"
        )
    observed_percent = float(value) * 100.0
    result["observed_percent"] = observed_percent
    if abs(observed_percent - percent) > tolerance_percent:
        raise RuntimeError(
            f"Screen brightness is {observed_percent:.1f}%, expected {percent}% (+/- {tolerance_percent}%)."
        )
    return result


def browser_versions() -> dict[str, str | None]:
    apps = {
        "chrome": "/Applications/Google Chrome.app",
        "safari": "/Applications/Safari.app",
        "edge": "/Applications/Microsoft Edge.app",
        "firefox": "/Applications/Firefox.app",
        "zen": "/Applications/Zen.app",
    }
    out: dict[str, str | None] = {}
    for key, app in apps.items():
        plist = Path(app) / "Contents" / "Info.plist"
        if not plist.exists():
            out[key] = None
            continue
        try:
            with plist.open("rb") as f:
                info = plistlib.load(f)
            out[key] = info.get("CFBundleShortVersionString") or info.get(
                "CFBundleVersion"
            )
        except Exception:
            out[key] = None
    return out


def battery_status() -> BatteryStatus:
    pmset = run_cmd(["pmset", "-g", "batt"])
    percent: int | None = None
    source: str | None = None
    charging: bool | None = None
    if pmset.stdout:
        first = pmset.stdout.splitlines()[0] if pmset.stdout.splitlines() else ""
        if "'" in first:
            source = first.split("'")[1]
        match = re.search(r"(\d+)%;\s*([^;]+);", pmset.stdout)
        if match:
            percent = int(match.group(1))
            charging = (
                "charging" in match.group(2).lower()
                and "discharging" not in match.group(2).lower()
            )

    voltage = amperage = current_capacity = max_capacity = design_capacity = None
    ioreg = run_cmd(["ioreg", "-rn", "AppleSmartBattery"])
    if ioreg.stdout:
        voltage = _ioreg_int(ioreg.stdout, "AppleRawBatteryVoltage") or _ioreg_int(
            ioreg.stdout, "Voltage"
        )
        amperage = _signed(
            _ioreg_int(ioreg.stdout, "InstantAmperage")
            or _ioreg_int(ioreg.stdout, "Amperage")
        )
        current_capacity = _ioreg_int(
            ioreg.stdout, "AppleRawCurrentCapacity"
        ) or _ioreg_int(ioreg.stdout, "CurrentCapacity")
        max_capacity = (
            _ioreg_int(ioreg.stdout, "AppleRawMaxCapacity")
            or _ioreg_int(ioreg.stdout, "NominalChargeCapacity")
            or _ioreg_int(ioreg.stdout, "MaxCapacity")
        )
        design_capacity = _ioreg_int(ioreg.stdout, "DesignCapacity")

    watts = None
    if voltage is not None and amperage is not None:
        watts = abs(voltage * amperage) / 1_000_000.0

    return BatteryStatus(
        timestamp=time.time(),
        percent=percent,
        power_source=source,
        is_charging=charging,
        voltage_mv=voltage,
        amperage_ma=amperage,
        instant_watts=watts,
        current_capacity_mah=current_capacity,
        max_capacity_mah=max_capacity,
        design_capacity_mah=design_capacity,
    )


def process_snapshot(browser: str) -> list[dict[str, Any]]:
    patterns = {
        "chrome": "Google Chrome",
        "safari": "Safari|com.apple.WebKit",
        "edge": "Microsoft Edge",
        "firefox": "Firefox",
        "zen": "Zen|zen",
    }
    pattern = patterns.get(browser, browser)
    proc = run_cmd(["ps", "-axo", "pid,ppid,%cpu,%mem,rss,comm"])
    rows: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines()[1:]:
        if not re.search(pattern, line, re.I):
            continue
        parts = line.split(None, 5)
        if len(parts) != 6:
            continue
        rows.append(
            {
                "timestamp": time.time(),
                "pid": parts[0],
                "ppid": parts[1],
                "cpu_percent": parts[2],
                "mem_percent": parts[3],
                "rss_kb": parts[4],
                "command": parts[5],
            }
        )
    return rows


def start_powermetrics(path: Path, interval_ms: int) -> subprocess.Popen[str] | None:
    if not command_exists("powermetrics"):
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    f = path.open("w", encoding="utf-8")
    cmd = ["powermetrics", "--samplers", "cpu_power,gpu_power", "-i", str(interval_ms)]
    if os.geteuid() != 0 and command_exists("sudo"):
        cmd = ["sudo", "-n", *cmd]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=f,
            stderr=subprocess.STDOUT,
            text=True,
        )
        f.close()
        return proc
    except Exception:
        f.close()
        return None


def stop_process(proc: subprocess.Popen[str] | None, timeout: float = 5) -> None:
    if proc is None:
        return
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=timeout)


def _current_pid() -> int:
    return os.getpid()


def _display_api():
    try:
        core_graphics = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
        )
        display_services = ctypes.cdll.LoadLibrary(
            "/System/Library/PrivateFrameworks/DisplayServices.framework/DisplayServices"
        )
        core_graphics.CGMainDisplayID.restype = ctypes.c_uint32
        display_services.DisplayServicesGetBrightness.argtypes = [
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_float),
        ]
        display_services.DisplayServicesGetBrightness.restype = ctypes.c_int
        display_services.DisplayServicesSetBrightness.argtypes = [
            ctypes.c_uint32,
            ctypes.c_float,
        ]
        display_services.DisplayServicesSetBrightness.restype = ctypes.c_int
        return core_graphics, display_services
    except Exception:
        return None


def _set_brightness_with_keys(percent: int) -> None:
    # macOS exposes brightness keys as coarse hardware steps. Use this only when
    # DisplayServices is unavailable; it is intentionally conservative.
    down = 145
    up = 144
    steps = round(max(0, min(100, percent)) / 100 * 16)
    script_lines = ['tell application "System Events"']
    script_lines.extend(f"  key code {down}" for _ in range(20))
    script_lines.extend(f"  key code {up}" for _ in range(steps))
    script_lines.append("end tell")
    run_cmd(["osascript", "-e", "\n".join(script_lines)])


def _ioreg_int(text: str, key: str) -> int | None:
    match = re.search(rf'"{re.escape(key)}"\s*=\s*(-?\d+)', text)
    return int(match.group(1)) if match else None


def _signed(value: int | None) -> int | None:
    if value is None:
        return None
    if value >= 2**63:
        return value - 2**64
    return value


def _cmd_lines(args: list[str]) -> list[str]:
    try:
        proc = run_cmd(args, timeout=15)
        return proc.stdout.splitlines() + proc.stderr.splitlines()
    except Exception as exc:
        return [f"ERROR: {exc}"]
