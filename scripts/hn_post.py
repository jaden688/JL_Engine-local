"""
Post a Show HN from a standalone Playwright process.
Usage: python scripts/hn_post.py
"""
from playwright.sync_api import sync_playwright
import sys, time

USERNAME = "sparkbyte"
PASSWORD = os.environ.get("HN_PASSWORD", "")
TITLE    = "Show HN: JL Engine – Local-first autonomous AI agent runtime built in Julia"
TEXT     = """JL Engine is a local-first autonomous AI agent platform built in Julia.

It runs multiple named agents (SparkByte, The Ironclad, Slappy, and others) with:
- Persistent memory and emotional state per agent
- Autopilot loop that acts independently on a schedule
- Tool execution: web browsing, shell commands, SMS, Reddit posting, code execution
- Agents can forge their own new tools at runtime
- Multi-agent coordination via A2A protocol
- Full WebSocket UI with live thought stream

No cloud required. Runs entirely on your local machine.

Built because Python wrappers were too slow and too shallow."""

SCREENSHOT = "C:/Users/J_lin/Desktop/hn_result.png"

def log(msg):
    print(f"[hn_post] {msg}", flush=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()

    log("navigating to login...")
    page.goto("https://news.ycombinator.com/login", wait_until="load", timeout=30000)
    time.sleep(1)

    log("filling login form...")
    try:
        page.fill("input[name='acct']", USERNAME, timeout=10000)
        page.fill("input[name='pw']", PASSWORD, timeout=10000)
        page.click("input[type='submit']", timeout=10000)
        time.sleep(2)
        log(f"after login — url: {page.url}")
    except Exception as e:
        log(f"login step failed: {e}")
        page.screenshot(path=SCREENSHOT)
        browser.close()
        sys.exit(1)

    if "login" in page.url:
        log("ERROR: still on login page — wrong credentials or blocked")
        page.screenshot(path=SCREENSHOT)
        browser.close()
        sys.exit(1)

    log("navigating to submit...")
    page.goto("https://news.ycombinator.com/submit", wait_until="load", timeout=30000)
    time.sleep(1)

    log("filling post...")
    try:
        page.type("input[name='title']", TITLE, delay=80)
        page.type("textarea[name='text']", TEXT, delay=40)
        page.screenshot(path=SCREENSHOT.replace("result", "before_submit"))
        page.click("input[type='submit']", timeout=10000)
        time.sleep(3)
        log(f"submitted — url: {page.url}")
    except Exception as e:
        log(f"submit step failed: {e}")
        page.screenshot(path=SCREENSHOT)
        browser.close()
        sys.exit(1)

    page.screenshot(path=SCREENSHOT)
    log(f"screenshot saved to {SCREENSHOT}")
    log(f"final url: {page.url}")
    browser.close()
    log("done")

