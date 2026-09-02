import httpx
import time

BRIDGE_URL = "http://127.0.0.1:8765/api/action"
SHOT_DIR = r"C:\Users\hmoha\.gemini\antigravity-cli\brain\e635a2da-caba-4f7b-935f-ca805b610af5"

def run():
    print("Restarting browser to ensure no cache issues...")
    # Navigate to a blank page first to ensure clean state
    httpx.post(BRIDGE_URL, json={
        "action": "cdp_command",
        "params": {"method": "Page.navigate", "params": {"url": "about:blank"}}
    }, timeout=10.0)
    time.sleep(1)

    # Now navigate to the app, with cache bypassed
    httpx.post(BRIDGE_URL, json={
        "action": "cdp_command",
        "params": {"method": "Network.setCacheDisabled", "params": {"cacheDisabled": True}}
    }, timeout=10.0)
    
    httpx.post(BRIDGE_URL, json={
        "action": "cdp_command",
        "params": {"method": "Page.navigate", "params": {"url": "http://localhost:7002/"}}
    }, timeout=10.0)
    time.sleep(4.0)

    print("Clicking Projects button in sidebar...")
    expr_click = """
    (async () => {
        const btn = document.getElementById('tool-projects-btn');
        if (btn) btn.click();
        return { clicked: !!btn };
    })()
    """
    res = httpx.post(BRIDGE_URL, json={
        "action": "cdp_command",
        "params": {"method": "Runtime.evaluate", "params": {"expression": expr_click, "awaitPromise": True, "returnByValue": True}}
    }, timeout=10.0).json()
    print("JS RESULT:", res)
    
    time.sleep(2.0)
    
    import os
    shot = os.path.join(SHOT_DIR, "projects_landing_page_natural.png")
    httpx.post(BRIDGE_URL, json={"action": "screenshot", "save_screenshot_path": shot}, timeout=10.0)
    print(f"Screenshot saved to: {shot}")

if __name__ == "__main__":
    run()
