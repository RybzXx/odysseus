"""scripts/add_todo_test.py

Saves the 'work on gemini' todo note card and captures the result.
"""

import httpx
import time

BRIDGE_URL = "http://127.0.0.1:8765/api/action"
SHOT_PATH = r"C:\Users\hmoha\.gemini\antigravity-cli\brain\e635a2da-caba-4f7b-935f-ca805b610af5\notes_todo_saved_card.png"

def save_note():
    js_code = """
    (() => {
        // Find Save button in composer
        const btns = Array.from(document.querySelectorAll("button, .btn, [role='button']"));
        const saveBtn = btns.find(b => b.textContent.includes('Save') && b.offsetParent !== null);
        if (saveBtn) {
            saveBtn.click();
            return { success: true, text: saveBtn.textContent.trim() };
        }
        return { success: false, error: 'Save button not found' };
    })()
    """

    print("[*] Clicking Save button...")
    r = httpx.post(BRIDGE_URL, json={
        "action": "cdp_command",
        "params": {
            "method": "Runtime.evaluate",
            "params": {
                "expression": js_code,
                "returnByValue": True
            }
        }
    }, timeout=10.0)
    print("[+] Save click response:", r.json())

    time.sleep(2.0)

    # Capture screenshot
    print(f"[*] Capturing screenshot to {SHOT_PATH}...")
    s = httpx.post(BRIDGE_URL, json={
        "action": "screenshot",
        "save_screenshot_path": SHOT_PATH
    }, timeout=10.0)
    print(f"[+] Screenshot saved with status: {s.status_code}")

if __name__ == "__main__":
    save_note()
