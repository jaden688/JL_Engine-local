from __future__ import annotations

import os
from pathlib import Path
from queue import Empty, Queue
from threading import Event, RLock, Thread
from typing import Any, Dict


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _clip_text(value: Any, limit: int = 4000) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _windows_browser_candidates() -> list[tuple[str, str]]:
    if os.name != "nt":
        return []
    candidates = (
        ("msedge", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        ("msedge", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        ("chrome", r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        ("chrome", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    )
    discovered: list[tuple[str, str]] = []
    for browser_name, raw_path in candidates:
        path = Path(raw_path)
        if path.exists():
            discovered.append((browser_name, str(path)))
    return discovered


class BrowserBridgeManager:
    def __init__(self, *, headed: bool | None = None) -> None:
        default_headed = _env_bool("JL_BROWSER_HEADED", True)
        self._headed = bool(default_headed if headed is None else headed)
        self._channel = str(os.getenv("JL_BROWSER_CHANNEL", "") or "").strip() or None
        self._lock = RLock()
        self._jobs: Queue[tuple[str, dict[str, Any], Queue[Dict[str, Any]]]] | None = None
        self._worker: Thread | None = None
        self._stop_event = Event()
        self._state: Dict[str, Any] = {
            "status": "ok",
            "available": self._playwright_import_available(),
            "ready": False,
            "headed": self._headed,
            "channel": self._channel or "",
            "requested_channel": self._channel or "",
            "launch_strategy": "",
            "launch_candidates": [],
            "browser_path": "",
            "current_url": "",
            "title": "",
            "last_error": "",
            "capability_tier": "session_attach_accessibility",
        }
        self._update_state(launch_candidates=self._launch_candidate_labels())

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def shutdown(self) -> None:
        with self._lock:
            jobs = self._jobs
            worker = self._worker
        if jobs is None or worker is None:
            with self._lock:
                self._state["ready"] = False
                self._state["current_url"] = ""
                self._state["title"] = ""
            return

        reply_queue: Queue[Dict[str, Any]] = Queue(maxsize=1)
        jobs.put(("shutdown", {}, reply_queue))
        try:
            reply_queue.get(timeout=10)
        except Empty:
            pass
        worker.join(timeout=10)
        with self._lock:
            self._jobs = None
            self._worker = None
            self._stop_event = Event()
            self._state["ready"] = False
            self._state["current_url"] = ""
            self._state["title"] = ""

    def handle(self, payload: Dict[str, Any] | None) -> Dict[str, Any]:
        body = payload if isinstance(payload, dict) else {}
        request_type = str(body.get("request_type") or body.get("type") or "").strip().lower()
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        if request_type.endswith("inspect"):
            return self.inspect(data)
        if request_type.endswith("action"):
            return self.action(data)
        return self._error(
            "unknown_browser_request",
            f"Unsupported browser request: {request_type or '<empty>'}",
        )

    def inspect(self, data: Dict[str, Any] | None = None) -> Dict[str, Any]:
        payload = data if isinstance(data, dict) else {}
        return self._call_worker("inspect", payload)

    def action(self, data: Dict[str, Any] | None = None) -> Dict[str, Any]:
        payload = data if isinstance(data, dict) else {}
        return self._call_worker("action", payload)

    def _playwright_import_available(self) -> bool:
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except Exception:
            return False
        return True

    def _system_browser_executables(self) -> list[tuple[str, str]]:
        return _windows_browser_candidates()

    def _launch_candidates(self) -> list[Dict[str, Any]]:
        candidates: list[Dict[str, Any]] = []
        seen: set[tuple[tuple[str, str], ...]] = set()

        def add_candidate(label: str, *, browser_name: str = "", **kwargs: Any) -> None:
            normalized_kwargs = {key: str(value) for key, value in kwargs.items() if str(value or "").strip()}
            dedupe_key = tuple(sorted(normalized_kwargs.items()))
            if dedupe_key in seen:
                return
            seen.add(dedupe_key)
            candidates.append(
                {
                    "label": label,
                    "browser_name": browser_name,
                    "kwargs": normalized_kwargs,
                }
            )

        if self._channel:
            add_candidate(f"channel:{self._channel}", browser_name=self._channel, channel=self._channel)

        executable_by_name: dict[str, str] = {}
        for browser_name, browser_path in self._system_browser_executables():
            executable_by_name.setdefault(browser_name, browser_path)

        for browser_name in ("msedge", "chrome"):
            browser_path = executable_by_name.get(browser_name)
            if not browser_path:
                continue
            add_candidate(f"channel:{browser_name}", browser_name=browser_name, channel=browser_name)
            add_candidate(f"exe:{browser_name}", browser_name=browser_name, executable_path=browser_path)

        add_candidate("bundled:chromium")
        return candidates

    def _launch_candidate_labels(self) -> list[str]:
        return [str(candidate.get("label") or "").strip() for candidate in self._launch_candidates()]

    def _launch_browser(self, playwright):
        errors: list[str] = []
        for candidate in self._launch_candidates():
            launch_kwargs: Dict[str, Any] = {"headless": not self._headed}
            launch_kwargs.update(candidate.get("kwargs") or {})
            try:
                browser = playwright.chromium.launch(**launch_kwargs)
            except Exception as exc:
                errors.append(f"{candidate['label']}: {exc}")
                continue
            self._update_state(
                available=True,
                last_error="",
                launch_strategy=str(candidate.get("label") or ""),
                channel=str(candidate.get("browser_name") or candidate.get("kwargs", {}).get("channel") or ""),
                browser_path=str(candidate.get("kwargs", {}).get("executable_path") or ""),
            )
            return browser

        message = " | ".join(errors[-4:]) or "No browser launch strategy succeeded."
        self._update_state(
            available=True,
            ready=False,
            last_error=message,
            launch_strategy="",
            browser_path="",
        )
        raise RuntimeError(message)

    def _call_worker(self, job_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self._playwright_import_available():
            self._update_state(available=False, last_error="No module named 'playwright'")
            return self._error(
                "playwright_unavailable",
                "Install Playwright and Chromium to enable the local browser bridge.",
            )

        jobs = self._ensure_worker()
        if jobs is None:
            return self._error("browser_worker_unavailable", "Browser bridge worker failed to start.")
        reply_queue: Queue[Dict[str, Any]] = Queue(maxsize=1)
        jobs.put((job_type, payload, reply_queue))
        try:
            return reply_queue.get(timeout=60)
        except Empty:
            message = f"Timed out waiting for browser bridge {job_type}."
            self._update_state(last_error=message)
            return self._error("browser_bridge_timeout", message)

    def _ensure_worker(self) -> Queue[tuple[str, dict[str, Any], Queue[Dict[str, Any]]]] | None:
        with self._lock:
            if self._worker and self._worker.is_alive() and self._jobs is not None:
                return self._jobs
            self._jobs = Queue()
            self._stop_event = Event()
            self._worker = Thread(target=self._worker_main, name="jl-browser-bridge", daemon=True)
            self._worker.start()
            return self._jobs

    def _page_is_stale(self, page: Any, browser: Any) -> bool:
        if page is None:
            return True
        try:
            if hasattr(page, "is_closed") and page.is_closed():
                return True
        except Exception:
            return True
        try:
            if browser is not None and hasattr(browser, "is_connected") and not browser.is_connected():
                return True
        except Exception:
            return True
        return False

    def _worker_main(self) -> None:
        playwright = None
        browser = None
        context = None
        page = None

        def ensure_page():
            nonlocal playwright, browser, context, page
            if page is not None and not self._page_is_stale(page, browser):
                return page
            if page is not None:
                close_everything()
            from playwright.sync_api import sync_playwright

            playwright = sync_playwright().start()
            browser = self._launch_browser(playwright)
            context = browser.new_context()
            page = context.new_page()
            self._update_state(available=True, ready=True, last_error="")
            return page

        def close_everything() -> None:
            nonlocal playwright, browser, context, page
            for value, closer in (
                (page, "close"),
                (context, "close"),
                (browser, "close"),
                (playwright, "stop"),
            ):
                if value is None:
                    continue
                try:
                    getattr(value, closer)()
                except Exception:
                    pass
            page = None
            context = None
            browser = None
            playwright = None
            self._update_state(ready=False)

        while not self._stop_event.is_set():
            try:
                jobs = self._jobs
                if jobs is None:
                    break
                job_type, payload, reply_queue = jobs.get(timeout=0.2)
            except Empty:
                continue

            if job_type == "shutdown":
                close_everything()
                reply_queue.put({"status": "ok"})
                break

            try:
                current_page = ensure_page()
                if job_type == "inspect":
                    result = self._inspect_page(current_page, payload)
                elif job_type == "action":
                    result = self._act_on_page(current_page, payload)
                else:
                    result = self._error("unknown_browser_job", f"Unsupported browser worker job: {job_type}")
            except Exception as exc:
                close_everything()
                self._update_state(last_error=str(exc))
                result = self._error("browser_bridge_failed", str(exc))

            reply_queue.put(result)

        close_everything()

    def _inspect_page(self, page, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = str(payload.get("url") or "").strip()
        if url:
            nav_error = self._navigate(page, url)
            if nav_error:
                return nav_error
        dom = self._collect_dom_snapshot(page)
        ax_tree = self._capture_accessibility_tree(page) or dom.get("ax_tree")
        current_url = str(getattr(page, "url", "") or "").strip()
        title = _clip_text(page.title(), 300)
        self._update_state(current_url=current_url, title=title, ready=True, last_error="")
        return {
            "status": "ok",
            "capability_tier": "session_attach_accessibility",
            "url": current_url,
            "title": title,
            "focused": dom.get("focused"),
            "controls": dom.get("controls", []),
            "visible_text": _clip_text(dom.get("visible_text", ""), 4000),
            "dom_excerpt": _clip_text(dom.get("dom_excerpt", ""), 4000),
            "ax_tree": ax_tree,
            "message": "Browser page inspected.",
        }

    def _act_on_page(self, page, payload: Dict[str, Any]) -> Dict[str, Any]:
        action = str(payload.get("action") or payload.get("mode") or "").strip().lower()
        request_id = str(payload.get("request_id") or "").strip()

        if action in {"open", "navigate", "goto"}:
            url = str(payload.get("url") or "").strip()
            if not url:
                return self._error("missing_url", "Browser navigation requires a URL.")
            nav_error = self._navigate(page, url)
            if nav_error:
                return nav_error
        elif action in {"click", "focus", "type", "fill", "submit"}:
            locator = self._locate_target(page, payload)
            if isinstance(locator, dict):
                return locator
            if action == "click":
                locator.click(timeout=5000)
            elif action == "focus":
                locator.focus()
            elif action in {"type", "fill"}:
                value = str(payload.get("value") or payload.get("text") or "")
                locator.fill(value, timeout=5000)
            elif action == "submit":
                try:
                    locator.press("Enter", timeout=5000)
                except Exception:
                    locator.evaluate(
                        """(el) => {
                            if (el.form) {
                                el.form.requestSubmit ? el.form.requestSubmit() : el.form.submit();
                                return;
                            }
                            el.click?.();
                        }"""
                    )
            try:
                page.wait_for_load_state("domcontentloaded", timeout=1500)
            except Exception:
                pass
        elif action in {"inspect", "inspect_page"}:
            return self._inspect_page(page, payload)
        else:
            return self._error("unsupported_action", f"Unsupported browser action: {action or '<empty>'}")

        current_url = str(getattr(page, "url", "") or "").strip()
        title = _clip_text(page.title(), 300)
        self._update_state(current_url=current_url, title=title, ready=True, last_error="")
        return {
            "status": "ok",
            "capability_tier": "session_attach_accessibility",
            "action": action,
            "request_id": request_id,
            "url": current_url,
            "title": title,
            "message": f"Browser action completed: {action}",
        }

    def _navigate(self, page, url: str) -> Dict[str, Any] | None:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            try:
                page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                pass
            return None
        except Exception as exc:
            self._update_state(last_error=str(exc))
            return self._error("browser_navigation_failed", str(exc), url=url)

    def _capture_accessibility_tree(self, page) -> Any:
        try:
            accessibility = getattr(page, "accessibility", None)
            if accessibility and hasattr(accessibility, "snapshot"):
                return accessibility.snapshot(interesting_only=True)
        except Exception:
            pass
        return None

    def _collect_dom_snapshot(self, page) -> Dict[str, Any]:
        script = """
        () => {
          const text = (value) => String(value || "").replace(/\\s+/g, " ").trim();
          const inferRole = (el) => {
            const explicit = text(el.getAttribute("role"));
            if (explicit) return explicit;
            const tag = (el.tagName || "").toLowerCase();
            if (tag === "a") return "link";
            if (tag === "button") return "button";
            if (tag === "select") return "combobox";
            if (tag === "textarea") return "textbox";
            if (tag === "input") {
              const type = text(el.getAttribute("type")) || "text";
              if (["button", "submit", "reset"].includes(type)) return "button";
              if (["checkbox"].includes(type)) return "checkbox";
              if (["radio"].includes(type)) return "radio";
              return "textbox";
            }
            return tag;
          };
          const inferName = (el) => {
            return text(
              el.getAttribute("aria-label") ||
              el.getAttribute("title") ||
              el.getAttribute("placeholder") ||
              el.getAttribute("name") ||
              el.getAttribute("alt") ||
              el.innerText ||
              el.value ||
              el.textContent
            );
          };
          const inferState = (el) => {
            const parts = [];
            if (el.disabled) parts.push("disabled");
            if (el.checked === true) parts.push("checked");
            if (el.getAttribute("aria-expanded") === "true") parts.push("expanded");
            if (el === document.activeElement) parts.push("focused");
            return parts.join(", ");
          };
          const controls = [];
          const seen = new Set();
          const nodes = document.querySelectorAll("a,button,input,select,textarea,[role],[tabindex]");
          for (const el of nodes) {
            if (controls.length >= 100) break;
            const key = text(el.id) || text(el.outerHTML).slice(0, 120);
            if (key && seen.has(key)) continue;
            if (key) seen.add(key);
            controls.push({
              role: inferRole(el),
              name: inferName(el).slice(0, 200),
              id: text(el.id),
              value: text(el.value).slice(0, 200),
              state: inferState(el).slice(0, 200),
            });
          }
          const active = document.activeElement;
          const axLike = [];
          const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_ELEMENT);
          while (walker.nextNode() && axLike.length < 120) {
            const el = walker.currentNode;
            const role = inferRole(el);
            const name = inferName(el);
            if (!role && !name) continue;
            axLike.push({
              role,
              name: name.slice(0, 200),
              id: text(el.id),
            });
          }
          return {
            visible_text: text(document.body && document.body.innerText).slice(0, 12000),
            dom_excerpt: String((document.body && document.body.innerHTML) || "").slice(0, 12000),
            focused: active ? {
              role: inferRole(active),
              name: inferName(active).slice(0, 200),
              id: text(active.id),
            } : null,
            controls,
            ax_tree: {
              role: "document",
              name: text(document.title),
              children: axLike,
            },
          };
        }
        """
        try:
            data = page.evaluate(script)
            if isinstance(data, dict):
                return data
        except Exception as exc:
            self._update_state(last_error=str(exc))
        return {
            "visible_text": "",
            "dom_excerpt": "",
            "focused": None,
            "controls": [],
            "ax_tree": None,
        }

    def _locate_target(self, page, payload: Dict[str, Any]):
        target = payload.get("target") if isinstance(payload.get("target"), dict) else {}
        selector = self._first_non_empty(payload.get("selector"), target.get("selector"))
        if selector:
            locator = self._try_locator(page.locator(selector).first)
            if locator is not None:
                return locator

        element_id = self._first_non_empty(payload.get("id"), target.get("id"))
        if element_id:
            locator = self._try_locator(page.locator(f'[id="{self._css_attr(element_id)}"]').first)
            if locator is not None:
                return locator

        role = self._first_non_empty(payload.get("role"), target.get("role"))
        name = self._first_non_empty(
            payload.get("name"),
            target.get("name"),
            payload.get("label"),
            target.get("label"),
        )
        if role and name:
            try:
                locator = self._try_locator(page.get_by_role(role, name=name).first)
                if locator is not None:
                    return locator
            except Exception:
                pass

        if name:
            for candidate in (
                lambda: page.get_by_label(name).first,
                lambda: page.get_by_placeholder(name).first,
                lambda: page.get_by_text(name, exact=True).first,
                lambda: page.get_by_text(name).first,
            ):
                try:
                    locator = self._try_locator(candidate())
                except Exception:
                    locator = None
                if locator is not None:
                    return locator

        return self._error(
            "target_not_found",
            "Could not resolve a browser target. Provide selector, id, or role/name.",
        )

    def _try_locator(self, locator):
        try:
            if locator.count() > 0:
                return locator
        except Exception:
            return None
        return None

    def _css_attr(self, value: str) -> str:
        return str(value or "").replace("\\", "\\\\").replace('"', '\\"')

    def _first_non_empty(self, *values: Any) -> str:
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return ""

    def _update_state(self, **changes: Any) -> None:
        with self._lock:
            self._state.update(changes)

    def _error(self, code: str, message: str, **extra: Any) -> Dict[str, Any]:
        payload = {
            "status": "error",
            "error": code,
            "message": message,
            "capability_tier": "session_attach_accessibility",
        }
        payload.update(extra)
        return payload
