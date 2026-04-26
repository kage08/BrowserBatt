from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from subprocess import TimeoutExpired

from .util import run_cmd


@dataclass(frozen=True)
class BrowserSpec:
    key: str
    app_name: str
    bundle_path: str


BROWSERS: dict[str, BrowserSpec] = {
    "chrome": BrowserSpec("chrome", "Google Chrome", "/Applications/Google Chrome.app"),
    "safari": BrowserSpec("safari", "Safari", "/Applications/Safari.app"),
    "edge": BrowserSpec("edge", "Microsoft Edge", "/Applications/Microsoft Edge.app"),
    "firefox": BrowserSpec("firefox", "Firefox", "/Applications/Firefox.app"),
}


class BrowserController:
    def __init__(self, browser: str, viewport_width: int, viewport_height: int) -> None:
        if browser not in BROWSERS:
            raise ValueError(f"Unknown browser: {browser}")
        self.spec = BROWSERS[browser]
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height

    @property
    def key(self) -> str:
        return self.spec.key

    def installed(self) -> bool:
        return Path(self.spec.bundle_path).exists()

    def quit(self) -> None:
        try:
            run_cmd(["osascript", "-e", f'tell application "{self.spec.app_name}" to quit'], timeout=5)
        except TimeoutExpired:
            run_cmd(["osascript", "-e", f'tell application "System Events" to tell process "{self.spec.app_name}" to quit'], timeout=5)
        deadline = time.time() + 20
        while time.time() < deadline:
            if not self.is_running():
                return
            time.sleep(0.5)

    def is_running(self) -> bool:
        proc = run_cmd(["pgrep", "-x", self.spec.app_name])
        return proc.returncode == 0

    def launch_clean(self) -> None:
        self.quit()
        run_cmd(["open", "-a", self.spec.app_name], timeout=10)
        time.sleep(4)
        self.activate(required=False)
        self.close_all_windows()
        self.new_window()
        self.resize_front_window()
        time.sleep(1)

    def activate(self, required: bool = True) -> None:
        errors: list[str] = []
        try:
            run_cmd(["open", "-a", self.spec.app_name], timeout=8, check=True)
            time.sleep(0.5)
            return
        except Exception as exc:
            errors.append(f"open: {exc!r}")

        try:
            run_cmd(["osascript", "-e", f'tell application "{self.spec.app_name}" to activate'], timeout=8, check=True)
            time.sleep(0.5)
            return
        except Exception as exc:
            errors.append(f"app_activate: {exc!r}")

        script = f'''
        tell application "System Events"
          if exists process "{self.spec.app_name}" then
            set frontmost of process "{self.spec.app_name}" to true
          end if
        end tell
        '''
        try:
            run_cmd(["osascript", "-e", script], timeout=5, check=True)
            time.sleep(0.5)
            return
        except Exception as exc:
            errors.append(f"system_events_frontmost: {exc!r}")

        if required:
            raise RuntimeError(f"Could not activate {self.spec.app_name}: {'; '.join(errors)}")
        time.sleep(0.5)

    def close_all_windows(self) -> None:
        self.activate(required=False)
        # App-level close commands can hang on restored tabs or modal prompts, so
        # every path here has a short timeout and a keyboard fallback.
        script = f'tell application "{self.spec.app_name}" to close every window'
        try:
            run_cmd(["osascript", "-e", script], timeout=3)
        except TimeoutExpired:
            pass
        try:
            self.keystroke("w", modifiers=["command", "option"], timeout=3)
        except TimeoutExpired:
            pass
        time.sleep(0.5)
        self._dismiss_common_dialogs()
        time.sleep(0.5)

    def new_window(self) -> None:
        self.activate()
        self.keystroke("n", modifiers=["command"])
        time.sleep(1)

    def resize_front_window(self) -> None:
        script = f'''
        tell application "System Events"
          tell process "{self.spec.app_name}"
            if (count of windows) > 0 then
              set position of front window to {{0, 25}}
              set size of front window to {{{self.viewport_width}, {self.viewport_height}}}
            end if
          end tell
        end tell
        '''
        try:
            run_cmd(["osascript", "-e", script], timeout=3, check=True)
        except Exception:
            # Window sizing is useful for consistency but not worth failing a
            # long benchmark. The viewport is recorded in config metadata.
            return

    def open_url(self, url: str, wait_seconds: float = 5) -> None:
        self.activate()
        if not self._set_front_tab_url(url):
            self.key_code(37, modifiers=["command"])
            time.sleep(0.2)
            self.type_text(url)
            self.key_code(36)
        time.sleep(wait_seconds)

    def current_url(self) -> str | None:
        old_clipboard = run_cmd(["pbpaste"], timeout=2).stdout
        self.activate()
        try:
            self.keystroke("l", modifiers=["command"])
            time.sleep(0.2)
            self.keystroke("c", modifiers=["command"])
            time.sleep(0.2)
            proc = run_cmd(["pbpaste"], timeout=2)
            self.key_code(53)
            value = proc.stdout.strip()
            if value.startswith("http://") or value.startswith("https://"):
                return value
            return None
        finally:
            subprocess.run(["pbcopy"], input=old_clipboard, text=True, capture_output=True, timeout=2)

    def new_tab(self, url: str, wait_seconds: float = 5) -> None:
        self.activate()
        self.key_code(17, modifiers=["command"])
        time.sleep(0.3)
        self.type_text(url)
        self.key_code(36)
        time.sleep(wait_seconds)

    def switch_to_tab(self, index: int) -> None:
        if not 1 <= index <= 9:
            raise ValueError("macOS browser tab shortcuts support indexes 1-9")
        self.activate()
        self.keystroke(str(index), modifiers=["command"])
        time.sleep(0.5)

    def scroll(self, clicks: int) -> None:
        script = f'''
        tell application "System Events"
          tell process "{self.spec.app_name}"
            scroll down {clicks}
          end tell
        end tell
        '''
        run_cmd(["osascript", "-e", script], timeout=5)

    def page_down(self, count: int = 1, delay: float = 0.5) -> None:
        for _ in range(count):
            self.key_code(121)
            time.sleep(delay)

    def type_text(self, text: str) -> None:
        lines = text.split("\n")
        for index, line in enumerate(lines):
            if line:
                safe = line.replace("\\", "\\\\").replace('"', '\\"')
                self._system_events(f'keystroke "{safe}"')
            if index < len(lines) - 1:
                self.key_code(36)

    def type_text_slow(self, text: str, cadence: float) -> None:
        for chunk in _chunks(text, 60):
            self.type_text(chunk)
            time.sleep(max(cadence * len(chunk), 0.05))

    def keystroke(self, key: str, modifiers: list[str] | None = None, timeout: float | None = 5) -> None:
        if modifiers:
            using = " using {" + ", ".join(f"{m} down" for m in modifiers) + "}"
        else:
            using = ""
        self._system_events(f'keystroke "{key}"{using}', timeout=timeout or 15)

    def key_code(self, code: int, modifiers: list[str] | None = None) -> None:
        if modifiers:
            using = " using {" + ", ".join(f"{m} down" for m in modifiers) + "}"
        else:
            using = ""
        self._system_events(f"key code {code}{using}")

    def play_pause(self) -> None:
        self.keystroke("k")

    def close(self) -> None:
        self.quit()

    def _dismiss_common_dialogs(self) -> None:
        script = f'''
        tell application "System Events"
          tell process "{self.spec.app_name}"
            if exists sheet 1 of window 1 then
              key code 53
            end if
          end tell
        end tell
        '''
        try:
            run_cmd(["osascript", "-e", script], timeout=2)
        except TimeoutExpired:
            pass

    def _system_events(self, command: str, timeout: float = 15) -> None:
        script = f'tell application "System Events" to {command}'
        last_error: Exception | None = None
        for attempt_timeout in (timeout, max(timeout, 20)):
            try:
                run_cmd(["osascript", "-e", script], timeout=attempt_timeout, check=True)
                return
            except TimeoutExpired as exc:
                last_error = exc
            except Exception as exc:
                last_error = exc
                break
        raise RuntimeError(
            f"System Events command failed for {self.spec.app_name}: {command!r}. "
            "Grant Accessibility permission to the terminal/app running BrowserBatt, "
            "and close any modal prompts in the browser."
        ) from last_error

    def _set_front_tab_url(self, url: str) -> bool:
        escaped = url.replace("\\", "\\\\").replace('"', '\\"')
        if self.key in {"chrome", "edge"}:
            script = f'''
            tell application "{self.spec.app_name}"
              if (count of windows) = 0 then make new window
              set URL of active tab of front window to "{escaped}"
            end tell
            '''
        elif self.key == "safari":
            script = f'''
            tell application "{self.spec.app_name}"
              if (count of windows) = 0 then make new document
              set URL of current tab of front window to "{escaped}"
            end tell
            '''
        else:
            return False
        try:
            run_cmd(["osascript", "-e", script], timeout=8, check=True)
            return True
        except Exception:
            return False


def ensure_accessibility_hint() -> str:
    return (
        "If automation does not type/click, grant Accessibility permission to the terminal/app "
        "running BrowserBatt in System Settings -> Privacy & Security -> Accessibility."
    )


def _chunks(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]
