import httpx
import time

BRIDGE_URL = "http://127.0.0.1:8765/api/action"
SHOT_DIR = r"C:\Users\hmoha\.gemini\antigravity-cli\brain\e635a2da-caba-4f7b-935f-ca805b610af5"

def run():
    print("Reloading page...")
    httpx.post(BRIDGE_URL, json={
        "action": "cdp_command",
        "params": {"method": "Page.reload", "params": {"ignoreCache": True}}
    }, timeout=10.0)
    time.sleep(4.0)

    print("Opening projects hub...")
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

    import os
    shot = os.path.join(SHOT_DIR, "projects_landing_page_reloaded.png")
    httpx.post(BRIDGE_URL, json={"action": "screenshot", "save_screenshot_path": shot}, timeout=10.0)
    print(f"Screenshot saved to: {shot}")

if __name__ == "__main__":
    run()
