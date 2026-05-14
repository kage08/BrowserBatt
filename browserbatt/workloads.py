from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .browser import BrowserController
from .util import append_jsonl

DOC_TEXT = """BrowserBatt benchmark note.

This disposable document is being edited by an automated macOS benchmark. The text is intentionally ordinary: a few headings, short paragraphs, edits, and pauses to approximate daily document work. The benchmark measures browser power draw, not typing speed.

Notes:
- YouTube playback phase completed before this edit.
- The browser profile, extensions, and settings are the user's real configuration.
- This document should be deleted after the benchmark run.
"""

SHORT_DOC_TEXT = "BrowserBatt short smoke-test edit.\n"


class WorkloadRunner:
    def __init__(
        self, browser: BrowserController, events_path: Path, typing_cadence: float
    ) -> None:
        self.browser = browser
        self.events_path = events_path
        self.typing_cadence = typing_cadence

    def run(self, name: str, cfg: dict[str, Any], duration_seconds: int) -> None:
        if name == "daily":
            self.daily(cfg, duration_seconds)
        elif name == "media":
            self.media(cfg, duration_seconds)
        elif name == "reading":
            self.reading(cfg, duration_seconds)
        else:
            raise ValueError(f"Unknown workload: {name}")

    def daily(self, cfg: dict[str, Any], duration: int) -> None:
        deadline = time.monotonic() + max(0, duration)
        phases = [
            ("youtube", 0.30),
            ("docs", 0.25),
            ("news", 0.15),
            ("blog", 0.15),
            ("github", 0.15),
        ]
        tabs = self._open_daily_tabs(cfg)
        phase_budget = max(0, int(deadline - time.monotonic()))
        seconds = _phase_seconds(phases, phase_budget)
        self._work_daily_tab("youtube", tabs["youtube"], seconds["youtube"])
        self._work_daily_tab("docs", tabs["docs"], seconds["docs"])
        self._work_daily_tab("news", tabs.get("news", []), seconds["news"])
        self._work_daily_tab("blog", tabs.get("blog", []), seconds["blog"])
        self._work_daily_tab(
            "github", tabs["github"], max(0, int(deadline - time.monotonic()))
        )

    def media(self, cfg: dict[str, Any], duration: int) -> None:
        self._youtube(cfg["youtube_url"], duration)

    def reading(self, cfg: dict[str, Any], duration: int) -> None:
        phases = [("news", 0.35), ("blog", 0.30), ("github", 0.35)]
        seconds = _phase_seconds(phases, duration)
        self._reading_urls("news", cfg.get("news_urls", []), seconds["news"])
        self._reading_urls("blog", cfg.get("blog_urls", []), seconds["blog"])
        self._github(cfg["github_url"], seconds["github"])

    def _youtube(self, url: str, seconds: int) -> None:
        playback_url = _youtube_playback_url(url)
        self._event(
            "phase_start",
            phase="youtube",
            url=playback_url,
            configured_url=url,
            seconds=seconds,
        )
        self.browser.open_url(playback_url, wait_seconds=8)
        self._active_wait(seconds, action="youtube")
        self._event("phase_end", phase="youtube")

    def _open_daily_tabs(self, cfg: dict[str, Any]) -> dict[str, Any]:
        self._event("daily_tabs_setup_start")
        tabs: dict[str, Any] = {}
        index = 1

        youtube_url = cfg["youtube_url"]
        playback_url = _youtube_playback_url(youtube_url)
        self.browser.open_url(playback_url, wait_seconds=8)
        tabs["youtube"] = {
            "index": index,
            "url": playback_url,
            "configured_url": youtube_url,
        }
        self._event(
            "daily_tab_opened",
            phase="youtube",
            tab_index=index,
            url=playback_url,
            configured_url=youtube_url,
        )

        index += 1
        docs_url = cfg.get(
            "google_docs_url", "https://docs.google.com/document/u/0/create"
        )
        self.browser.new_tab(docs_url, wait_seconds=8)
        doc_url = self.browser.current_url()
        tabs["docs"] = {"index": index, "url": doc_url or docs_url}
        self._event(
            "daily_tab_opened",
            phase="google_docs",
            tab_index=index,
            url=doc_url or docs_url,
        )
        if doc_url and _is_google_doc_url(doc_url):
            self._event(
                "google_doc_created_or_opened",
                url=doc_url,
                cleanup="delete_after_benchmark",
            )

        news_tabs = []
        for url in cfg.get("news_urls", [])[:2]:
            index += 1
            self.browser.new_tab(url, wait_seconds=6)
            news_tabs.append({"index": index, "url": url})
            self._event("daily_tab_opened", phase="news", tab_index=index, url=url)
        tabs["news"] = news_tabs

        blog_tabs = []
        for url in cfg.get("blog_urls", [])[:2]:
            index += 1
            self.browser.new_tab(url, wait_seconds=6)
            blog_tabs.append({"index": index, "url": url})
            self._event("daily_tab_opened", phase="blog", tab_index=index, url=url)
        tabs["blog"] = blog_tabs

        index += 1
        github_url = cfg["github_url"]
        self.browser.new_tab(github_url, wait_seconds=6)
        tabs["github"] = {"index": index, "url": github_url}
        self._event("daily_tab_opened", phase="github", tab_index=index, url=github_url)
        self._event("daily_tabs_setup_end", tab_count=index)
        return tabs

    def _work_daily_tab(
        self, phase: str, tab_info: dict[str, Any] | list[dict[str, Any]], seconds: int
    ) -> None:
        if seconds <= 0:
            self._event("phase_skip", phase=phase, reason="no time remaining")
            return
        if isinstance(tab_info, list):
            if not tab_info:
                self._event("phase_skip", phase=phase, reason="no tabs configured")
                time.sleep(seconds)
                return
            allocations = _phase_seconds(
                [(str(i), 1 / len(tab_info)) for i in range(len(tab_info))], seconds
            )
            for i, info in enumerate(tab_info):
                self._work_daily_tab(phase, info, allocations[str(i)])
            return

        self.browser.switch_to_tab(tab_info["index"])
        event_phase = "google_docs" if phase == "docs" else phase
        self._event(
            "phase_start",
            phase=event_phase,
            url=tab_info.get("url"),
            tab_index=tab_info["index"],
            seconds=seconds,
        )
        if phase == "youtube":
            self._active_wait(seconds, action="youtube")
        elif phase == "docs":
            doc_text = DOC_TEXT if seconds >= 45 else SHORT_DOC_TEXT
            self.browser.type_text_slow(doc_text, self.typing_cadence)
            self.browser.keystroke("a", modifiers=["command"])
            time.sleep(0.5)
            self.browser.keystroke("b", modifiers=["command"])
            time.sleep(0.5)
            self.browser.keystroke("b", modifiers=["command"])
            self._active_wait(max(0, seconds - 20), action="docs")
        elif phase in {"news", "blog"}:
            self._active_wait(seconds, action="reading")
        elif phase == "github":
            self._active_wait(seconds // 2, action="github")
            self.browser.keystroke("f", modifiers=["command"])
            time.sleep(0.3)
            self.browser.type_text("README")
            time.sleep(1)
            self.browser.key_code(53)
            self._active_wait(seconds - seconds // 2, action="github")
        else:
            raise ValueError(f"Unknown daily tab phase: {phase}")
        self._event("phase_end", phase=event_phase, tab_index=tab_info["index"])

    def _docs(self, url: str, seconds: int) -> None:
        self._event("phase_start", phase="google_docs", url=url, seconds=seconds)
        self.browser.open_url(url, wait_seconds=8)
        time.sleep(2)
        doc_url = self.browser.current_url()
        if doc_url and _is_google_doc_url(doc_url):
            self._event(
                "google_doc_created_or_opened",
                url=doc_url,
                cleanup="delete_after_benchmark",
            )
        self.browser.type_text_slow(DOC_TEXT, self.typing_cadence)
        self.browser.keystroke("a", modifiers=["command"])
        time.sleep(0.5)
        self.browser.keystroke("b", modifiers=["command"])
        time.sleep(0.5)
        self.browser.keystroke("b", modifiers=["command"])
        self._active_wait(max(0, seconds - 20), action="docs")
        self._event("phase_end", phase="google_docs")

    def _reading_urls(self, phase: str, urls: list[str], seconds: int) -> None:
        if not urls:
            self._event("phase_skip", phase=phase, reason="no urls configured")
            time.sleep(seconds)
            return
        allocations = _phase_seconds(
            [(str(idx), 1 / len(urls)) for idx in range(len(urls))], seconds
        )
        for idx, url in enumerate(urls):
            per_url = allocations[str(idx)]
            self._event("phase_start", phase=phase, url=url, seconds=per_url, index=idx)
            self.browser.open_url(url, wait_seconds=6)
            self._active_wait(per_url, action="reading")
            self._event("phase_end", phase=phase, url=url, index=idx)

    def _github(self, url: str, seconds: int) -> None:
        self._event("phase_start", phase="github", url=url, seconds=seconds)
        self.browser.open_url(url, wait_seconds=6)
        self._active_wait(seconds // 2, action="github")
        self.browser.keystroke("f", modifiers=["command"])
        time.sleep(0.3)
        self.browser.type_text("README")
        time.sleep(1)
        self.browser.key_code(53)
        self._active_wait(seconds - seconds // 2, action="github")
        self._event("phase_end", phase="github")

    def _active_wait(self, seconds: int, action: str) -> None:
        deadline = time.monotonic() + max(0, seconds)
        i = 0
        while time.monotonic() < deadline:
            if action in {"reading", "github"}:
                self.browser.page_down(1, delay=0.2)
            elif action == "youtube":
                if i % 4 == 0:
                    self.browser.scroll(1)
            elif action == "docs":
                if i % 3 == 0:
                    self.browser.type_text_slow(
                        "\nAdditional benchmark sentence for editing cadence.",
                        self.typing_cadence,
                    )
            i += 1
            time.sleep(min(8, max(0, deadline - time.monotonic())))

    def _event(self, event: str, **data: Any) -> None:
        append_jsonl(
            self.events_path, {"timestamp": time.time(), "event": event, **data}
        )


def _phase_seconds(phases: list[tuple[str, float]], total: int) -> dict[str, int]:
    allocated = {name: int(total * fraction) for name, fraction in phases}
    remainder = total - sum(allocated.values())
    if phases:
        allocated[phases[-1][0]] += remainder
    return allocated


def _is_google_doc_url(url: str) -> bool:
    return url.startswith("https://docs.google.com/document/d/")


def _youtube_playback_url(url: str) -> str:
    parsed = urlsplit(url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params["autoplay"] = "1"
    query = urlencode(params)
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment)
    )
