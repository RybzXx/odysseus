import httpx
import time

BRIDGE_URL = "http://127.0.0.1:8765/api/action"

def run():
    httpx.post(BRIDGE_URL, json={
        "action": "cdp_command",
        "params": {"method": "Log.enable", "params": {}}
    }, timeout=10.0)
    httpx.post(BRIDGE_URL, json={
        "action": "cdp_command",
        "params": {"method": "Runtime.enable", "params": {}}
    }, timeout=10.0)
    
    expr = """
    (async () => {
        try {
            const mod = await import('/static/js/projects.js?v=' + Date.now());
            mod._currentProjectId = null;
            mod.openProjects();
            return "Started openProjects";
        } catch(e) {
            return "Import Error: " + e.stack;
        }
    })()
    """
    res = httpx.post(BRIDGE_URL, json={
        "action": "cdp_command",
        "params": {"method": "Runtime.evaluate", "params": {"expression": expr, "awaitPromise": True, "returnByValue": True}}
    }, timeout=10.0).json()
    print("JS RESULT:", res)
    
    time.sleep(2)
    # Check if we can extract logs somehow, but since it's just the CDP bridge we don't have event listeners.
    # Let's just screenshot
    shot = r"C:\Users\hmoha\.gemini\antigravity-cli\brain\e635a2da-caba-4f7b-935f-ca805b610af5\projects_landing_page_debug.png"
    httpx.post(BRIDGE_URL, json={"action": "screenshot", "save_screenshot_path": shot}, timeout=10.0)
    print("Saved to", shot)

if __name__ == "__main__":
    run()
