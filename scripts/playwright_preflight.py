#!/usr/bin/env python3
"""Check that async Playwright can launch and close Chromium cleanly."""
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
    print("ok")
