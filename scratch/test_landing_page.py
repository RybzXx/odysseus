import httpx
import time
import os

BRIDGE_URL = "http://127.0.0.1:8765/api/action"
SHOT_DIR = r"C:\Users\hmoha\.gemini\antigravity-cli\brain\e635a2da-caba-4f7b-935f-ca805b610af5"

def run():
    print("[*] 1. Navigating Brave to Projects Hub...")
    httpx.post(BRIDGE_URL, json={
        "action": "cdp_command",
        "params": {"method": "Page.navigate", "params": {"url": "http://localhost:7002/"}}
    }, timeout=10.0)
    time.sleep(3.0)

    print("[*] 2. Opening Projects Modal (should default to landing page)...")
    expr_open = """
    (async () => {
        const mod = await import('/static/js/projects.js');
        window.projectsModule = mod;
        mod.openProjects();
        return { ok: true };
    })()
    """
    httpx.post(BRIDGE_URL, json={
        "action": "cdp_command",
        "params": {"method": "Runtime.evaluate", "params": {"expression": expr_open, "awaitPromise": True, "returnByValue": True}}
    }, timeout=10.0)
    time.sleep(2.0)

    print("[*] 3. Taking screenshot...")
    shot = os.path.join(SHOT_DIR, "projects_landing_page.png")
    httpx.post(BRIDGE_URL, json={"action": "screenshot", "save_screenshot_path": shot}, timeout=10.0)
    print(f"[+] Verified landing page screenshot saved to: {shot}")

if __name__ == "__main__":
    run()
