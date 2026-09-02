import httpx
import time

BRIDGE_URL = "http://127.0.0.1:8765/api/action"

def run():
    print("Evaluating JS...")
    expr = """
    (async () => {
        let text = '';
        try {
            const mod = window.projectsModule;
            text += "Found mod. ";
            const btn = document.getElementById('proj-back-btn');
            if (btn) {
                text += "Found back button. Clicking... ";
                btn.click();
            } else {
                text += "No back button. Modifying DOM directly... ";
                mod._loadProjectDetail(null);
            }
        } catch (e) {
            text += "Error: " + e.toString();
        }
        return text;
    })()
    """
    res = httpx.post(BRIDGE_URL, json={
        "action": "cdp_command",
        "params": {"method": "Runtime.evaluate", "params": {"expression": expr, "awaitPromise": True, "returnByValue": True}}
    }, timeout=10.0).json()
    print("JS RESULT:", res.get('result', {}).get('result', {}).get('value'))
    
    time.sleep(1.0)
    shot = r"C:\Users\hmoha\.gemini\antigravity-cli\brain\e635a2da-caba-4f7b-935f-ca805b610af5\projects_landing_page_direct.png"
    httpx.post(BRIDGE_URL, json={"action": "screenshot", "save_screenshot_path": shot}, timeout=10.0)
    print(f"Screenshot saved to: {shot}")

if __name__ == "__main__":
    run()
