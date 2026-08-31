"""scripts/browser_agent.py

Interactive Brave / Chromium browser automation script for testing Odysseus at http://100.117.120.93:7000/
Supports:
- Direct Brave Browser launch (headful or headless)
- Existing Brave session attach via CDP (--cdp http://127.0.0.1:9222)
- Login automation (via --user and --pass flags)
- Visual screenshot capture at each interaction step
"""

import argparse
import os
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

DEFAULT_TARGET = "http://100.117.120.93:7000/"
DEFAULT_BRAVE_PATH = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"

def run_browser_session(
    url: str = DEFAULT_TARGET,
    screenshot_dir: str = "./screenshots",
    username: str = "",
    password: str = "",
    cdp_url: str = "",
    use_brave: bool = True,
    brave_path: str = DEFAULT_BRAVE_PATH,
    headless: bool = False,
):
    os.makedirs(screenshot_dir, exist_ok=True)
    shot_dir = Path(screenshot_dir)

    print(f"[*] Initializing browser automation session...")
    with sync_playwright() as p:
        if cdp_url:
            print(f"[*] Attaching to running browser at {cdp_url} via CDP...")
            browser = p.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.pages[0] if context.pages else context.new_page()
        else:
            launch_args = ["--start-maximized", "--disable-blink-features=AutomationControlled"]
            exec_path = None

            if use_brave and os.path.exists(brave_path):
                print(f"[*] Launching Brave Browser from: {brave_path} (headless={headless})...")
                exec_path = brave_path
            else:
                print(f"[*] Launching Chromium browser (headless={headless})...")

            browser = p.chromium.launch(
                executable_path=exec_path,
                headless=headless,
                args=launch_args,
            )
            context = browser.new_context(viewport=None)
            page = context.new_page()

        print(f"[*] Navigating to {url}...")
        try:
            resp = page.goto(url, timeout=15000, wait_until="domcontentloaded")
            print(f"[+] HTTP Status: {resp.status if resp else 'unknown'}")
        except Exception as e:
            print(f"[!] Navigation error: {e}")

        time.sleep(2)
        shot1 = shot_dir / "01_brave_initial_view.png"
        page.screenshot(path=str(shot1))
        print(f"[+] Screenshot saved: {shot1}")

        # Check if on Login page
        is_login = (
            page.locator("input[name='username'], input[type='text']").count() > 0
            and page.locator("button[type='submit'], button:has-text('Sign In')").count() > 0
        )
        if is_login and username and password:
            print(f"[*] Logging in as user '{username}'...")
            try:
                user_input = page.locator("input[name='username'], input[type='text']").first
                pass_input = page.locator("input[name='password'], input[type='password']").first
                submit_btn = page.locator("button:has-text('Sign In'), button[type='submit']").first

                user_input.fill(username)
                pass_input.fill(password)
                submit_btn.click()

                time.sleep(2.5)
                shot2 = shot_dir / "02_after_login.png"
                page.screenshot(path=str(shot2))
                print(f"[+] Post-login screenshot saved: {shot2}")
            except Exception as e:
                print(f"[!] Login error: {e}")

        # Inspect navigation elements
        rail_projects = page.locator("#rail-projects")
        tool_projects = page.locator("#tool-projects-btn")
        rail_ops = page.locator("#rail-operations")

        has_rail_p = rail_projects.count() > 0
        has_tool_p = tool_projects.count() > 0
        print(f"[*] #rail-projects present: {has_rail_p}")
        print(f"[*] #tool-projects-btn present: {has_tool_p}")
        print(f"[*] #rail-operations present: {rail_ops.count() > 0}")

        # Test opening Projects Modal
        if has_tool_p or has_rail_p:
            print("[*] Opening Projects Modal...")
            try:
                if has_tool_p and tool_projects.is_visible():
                    tool_projects.click()
                elif has_rail_p:
                    rail_projects.click()

                time.sleep(1.5)
                shot3 = shot_dir / "03_projects_modal_open.png"
                page.screenshot(path=str(shot3))
                print(f"[+] Projects modal screenshot saved: {shot3}")

                # Test clicking New Project button if modal is open
                new_proj_btn = page.locator("#proj-new-btn, button:has-text('New Project')")
                if new_proj_btn.count() > 0 and new_proj_btn.is_visible():
                    print("[*] Clicking New Project button...")
                    new_proj_btn.click()
                    time.sleep(1)
                    shot4 = shot_dir / "04_new_project_dialog.png"
                    page.screenshot(path=str(shot4))
                    print(f"[+] New project dialog screenshot saved: {shot4}")

            except Exception as e:
                print(f"[!] Error interacting with Projects: {e}")

        print("[+] Brave session complete.")
        return str(shot1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Odysseus Brave Browser Automation Agent")
    parser.add_argument("--url", default=DEFAULT_TARGET, help="Target URL")
    parser.add_argument("--shots", default="./screenshots", help="Screenshot output directory")
    parser.add_argument("--user", default="", help="Odysseus username")
    parser.add_argument("--pass", dest="password", default="", help="Odysseus password")
    parser.add_argument("--cdp", default="", help="Connect over Chrome DevTools Protocol URL")
    parser.add_argument("--brave", action="store_true", default=True, help="Use Brave browser executable")
    parser.add_argument("--brave-path", default=DEFAULT_BRAVE_PATH, help="Path to brave.exe")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")

    args = parser.parse_args()
    run_browser_session(
        url=args.url,
        screenshot_dir=args.shots,
        username=args.user,
        password=args.password,
        cdp_url=args.cdp,
        use_brave=args.brave,
        brave_path=args.brave_path,
        headless=args.headless,
    )
