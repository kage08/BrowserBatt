from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from subprocess import TimeoutExpired

from .util import run_cmd

CHROMIUM_BROWSER_KEYS = {"chrome", "edge"}


@dataclass(frozen=True)
class BrowserSpec:
    key: str
    app_name: str
    bundle_path: str
    process_name: str | None = None


BROWSERS: dict[str, BrowserSpec] = {
    "chrome": BrowserSpec("chrome", "Google Chrome", "/Applications/Google Chrome.app"),
    "safari": BrowserSpec("safari", "Safari", "/Applications/Safari.app"),
    "edge": BrowserSpec("edge", "Microsoft Edge", "/Applications/Microsoft Edge.app"),
    "firefox": BrowserSpec(
        "firefox", "Firefox", "/Applications/Firefox.app", process_name="firefox"
    ),
    "zen": BrowserSpec("zen", "Zen", "/Applications/Zen.app", process_name="zen"),
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
        if not self.is_running():
            return
        process_name = self.spec.process_name or self.spec.app_name
        try:
            proc = run_cmd(
                ["osascript", "-e", f'tell application "{self.spec.app_name}" to quit'],
                timeout=5,
            )
        except TimeoutExpired:
            proc = None
        if proc is None or proc.returncode != 0:
            try:
                run_cmd(
                    [
                        "osascript",
                        "-e",
                        f'tell application "System Events" to tell process "{self.spec.app_name}" to quit',
                    ],
                    timeout=5,
                )
            except TimeoutExpired:
                pass
        deadline = time.time() + 20
        while time.time() < deadline:
            if not self.is_running():
                return
            time.sleep(0.5)
        run_cmd(["pkill", "-TERM", "-x", process_name], timeout=5)
        deadline = time.time() + 10
        while time.time() < deadline:
            if not self.is_running():
                return
            time.sleep(0.5)
        raise RuntimeError(f"{self.spec.app_name} did not quit cleanly")

    def is_running(self) -> bool:
        proc = run_cmd(["pgrep", "-x", self.spec.process_name or self.spec.app_name])
        return proc.returncode == 0

    def launch_clean(self) -> None:
        self.quit()
        self._open_for_clean_launch()
        self._wait_until_running()
        time.sleep(3)
        self.activate(required=False)
        self._normalize_single_window()
        self.resize_front_window()
        time.sleep(1)

    def _open_for_clean_launch(self) -> None:
        args = ["open", "-a", self.spec.app_name]
        if self.key in CHROMIUM_BROWSER_KEYS:
            args += [
                "--args",
                "--disable-session-crashed-bubble",
                "--no-first-run",
                "--new-window",
                "about:blank",
            ]
        run_cmd(args, timeout=10, check=True)

    def _wait_until_running(self) -> None:
        deadline = time.time() + 30
        while time.time() < deadline:
            if self.is_running():
                return
            time.sleep(0.25)
        raise RuntimeError(f"{self.spec.app_name} did not start")

    def activate(self, required: bool = True) -> None:
        errors: list[str] = []
        try:
            run_cmd(["open", "-a", self.spec.app_name], timeout=8, check=True)
            time.sleep(0.5)
            return
        except Exception as exc:
            errors.append(f"open: {exc!r}")

        try:
            run_cmd(
                [
                    "osascript",
                    "-e",
                    f'tell application "{self.spec.app_name}" to activate',
                ],
                timeout=8,
                check=True,
            )
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
            raise RuntimeError(
                f"Could not activate {self.spec.app_name}: {'; '.join(errors)}"
            )
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

    def _normalize_single_window(self) -> None:
        # Chromium can restore crashed sessions a moment after first launch. Loop
        # briefly so restored empty/session windows are closed before sampling.
        for _ in range(3):
            self.close_all_windows()
            time.sleep(1)
            if self._window_count() == 0:
                break
        self.new_window()
        time.sleep(1)
        self._close_background_windows()

    def _window_count(self) -> int:
        script = f'''
        tell application "{self.spec.app_name}"
          return count of windows
        end tell
        '''
        try:
            proc = run_cmd(["osascript", "-e", script], timeout=3, check=True)
        except Exception:
            return 0
        try:
            return int(proc.stdout.strip())
        except ValueError:
            return 0

    def _close_background_windows(self) -> None:
        script = f'''
        tell application "{self.spec.app_name}"
          repeat while (count of windows) > 1
            close window 2
          end repeat
        end tell
        '''
        try:
            run_cmd(["osascript", "-e", script], timeout=3)
        except TimeoutExpired:
            pass

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
            subprocess.run(
                ["pbcopy"],
                input=old_clipboard,
                text=True,
                capture_output=True,
                timeout=2,
            )

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

    def keystroke(
        self, key: str, modifiers: list[str] | None = None, timeout: float | None = 5
    ) -> None:
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
                run_cmd(
                    ["osascript", "-e", script], timeout=attempt_timeout, check=True
                )
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
