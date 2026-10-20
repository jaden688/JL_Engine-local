"""
SparkByte HN Agent
Logs into Hacker News, browses projects, upvotes, comments, submits.
Credentials loaded from .env (HN_USERNAME / HN_PASSWORD).
"""

import os, sys, time, random, argparse
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

load_dotenv(Path(__file__).parent.parent / ".env")

HN_USER = os.getenv("HN_USERNAME", "sparkbyte")
HN_PASS = os.getenv("HN_PASSWORD", "")
HN_BASE = "https://news.ycombinator.com"

OLD_PASS = "3Irbfgvs!"  # rotate away from this on first run

def _human_delay(lo=0.4, hi=1.2):
    time.sleep(random.uniform(lo, hi))

def login(page):
    page.goto(f"{HN_BASE}/login")
    page.fill('input[name="acct"]', HN_USER)
    _human_delay()
    page.fill('input[name="pw"]', HN_PASS)
    _human_delay()
    page.click('input[type="submit"]')
    page.wait_for_load_state("networkidle")
    if "Bad login" in page.content():
        raise RuntimeError("HN login failed — check credentials in .env")
    print(f"[hn] logged in as {HN_USER}")

def rotate_password(page):
    """Change password from OLD_PASS to HN_PASS if needed."""
    page.goto(f"{HN_BASE}/login")
    page.fill('input[name="acct"]', HN_USER)
    _human_delay()
    page.fill('input[name="pw"]', OLD_PASS)
    _human_delay()
    page.click('input[type="submit"]')
    page.wait_for_load_state("networkidle")
    if "Bad login" in page.content():
        print("[hn] old password already rotated — skipping")
        return
    # Navigate to change password page
    page.goto(f"{HN_BASE}/user?id={HN_USER}")
    _human_delay(0.5, 1.0)
    # HN change password: fill change form
    page.goto(f"{HN_BASE}/changepw")
    _human_delay()
    page.fill('input[name="oldpw"]', OLD_PASS)
    _human_delay(0.3, 0.7)
    page.fill('input[name="newpw"]', HN_PASS)
    _human_delay(0.3, 0.7)
    page.fill('input[name="newpw2"]', HN_PASS)
    _human_delay()
    page.click('input[type="submit"]')
    page.wait_for_load_state("networkidle")
    print("[hn] password rotated successfully")

def browse_show_hn(page, limit=10):
    """Browse Show HN posts and return list of {title, url, points, id}."""
    page.goto(f"{HN_BASE}/show")
    page.wait_for_load_state("networkidle")
    items = page.query_selector_all(".athing")
    results = []
    for item in items[:limit]:
        try:
            item_id = item.get_attribute("id")
            title_el = item.query_selector(".titleline a")
            title = title_el.inner_text() if title_el else ""
            href = title_el.get_attribute("href") if title_el else ""
            subtext = page.query_selector(f"#score_{item_id}")
            points = subtext.inner_text() if subtext else "?"
            results.append({"id": item_id, "title": title, "url": href, "points": points})
        except Exception:
            pass
    return results

def upvote(page, item_id):
    """Upvote a post by ID."""
    up_btn = page.query_selector(f"#up_{item_id}")
    if up_btn:
        up_btn.click()
        _human_delay()
        print(f"[hn] upvoted {item_id}")
    else:
        print(f"[hn] already voted or can't find upvote for {item_id}")

def comment(page, item_id, text):
    """Leave a comment on a post."""
    page.goto(f"{HN_BASE}/item?id={item_id}")
    page.wait_for_load_state("networkidle")
    _human_delay(0.5, 1.0)
    textarea = page.query_selector('textarea[name="text"]')
    if not textarea:
        print(f"[hn] no comment box found for {item_id}")
        return
    textarea.click()
    _human_delay(0.2, 0.5)
    textarea.fill(text)
    _human_delay(0.5, 1.2)
    page.click('input[type="submit"]')
    page.wait_for_load_state("networkidle")
    print(f"[hn] commented on {item_id}")

def submit(page, title, url="", text=""):
    """Submit a new post."""
    page.goto(f"{HN_BASE}/submit")
    page.wait_for_load_state("networkidle")
    _human_delay(0.4, 0.8)
    page.fill('input[name="title"]', title)
    _human_delay(0.3, 0.6)
    if url:
        page.fill('input[name="url"]', url)
    if text:
        ta = page.query_selector('textarea[name="text"]')
        if ta:
            ta.fill(text)
    _human_delay(0.5, 1.0)
    page.click('input[type="submit"]')
    page.wait_for_load_state("networkidle")
    print(f"[hn] submitted: {title}")

def main():
    ap = argparse.ArgumentParser(description="SparkByte HN Agent")
    ap.add_argument("action", choices=["browse","upvote","comment","submit","rotate-pw"], help="Action to perform")
    ap.add_argument("--id", help="HN item ID (for upvote/comment)")
    ap.add_argument("--text", help="Comment text or post body")
    ap.add_argument("--title", help="Post title (for submit)")
    ap.add_argument("--url", default="", help="Post URL (for submit)")
    ap.add_argument("--limit", type=int, default=10, help="Number of posts to browse")
    ap.add_argument("--headless", action="store_true", default=True, help="Run headless")
    args = ap.parse_args()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=args.headless)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()

        if args.action == "rotate-pw":
            rotate_password(page)
        else:
            login(page)
            if args.action == "browse":
                posts = browse_show_hn(page, args.limit)
                for p in posts:
                    print(f"  [{p['points']}] {p['title']}  ({p['id']})")
            elif args.action == "upvote":
                if not args.id: ap.error("--id required")
                upvote(page, args.id)
            elif args.action == "comment":
                if not args.id or not args.text: ap.error("--id and --text required")
                comment(page, args.id, args.text)
            elif args.action == "submit":
                if not args.title: ap.error("--title required")
                submit(page, args.title, args.url, args.text or "")

        browser.close()

if __name__ == "__main__":
    main()
