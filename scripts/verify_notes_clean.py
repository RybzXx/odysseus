"""scripts/verify_notes_clean.py"""
import httpx
import time

BRIDGE_URL = "http://127.0.0.1:8765/api/action"
SHOT_DIR = r"C:\Users\hmoha\.gemini\antigravity-cli\brain\e635a2da-caba-4f7b-935f-ca805b610af5"

def run():
    # 1. Select option on #proj-select
    print("[*] 1. Selecting Odysseus Deep Workspace...")
    res = httpx.post(BRIDGE_URL, json={
        "action": "select_option",
        "params": {"selector": "#proj-select", "value": "proj_5e475d3c"}
    }, timeout=10.0)
    print("Select result:", res.json())
    time.sleep(2.0)

    # 2. Click To-Dos / Notes Tab
    print("[*] 2. Clicking Notes tab...")
    httpx.post(BRIDGE_URL, json={
        "action": "click",
        "params": {"selector": '[data-tab="tasks"]'}
    }, timeout=10.0)
    time.sleep(1.5)

    # 3. Scroll down in #proj-body
    print("[*] 3. Scrolling down to show cards...")
    httpx.post(BRIDGE_URL, json={
        "action": "scroll",
        "params": {"selector": "#proj-body", "y": 260}
    }, timeout=10.0)
    time.sleep(1.5)

    # 4. Take screenshot of cards
    shot = f"{SHOT_DIR}\\notes_extensive_parity_verified.png"
    httpx.post(BRIDGE_URL, json={"action": "screenshot", "save_screenshot_path": shot}, timeout=10.0)
    print("[+] Saved notes screenshot to:", shot)

    # 5. Click the image to trigger Lightbox Modal
    print("[*] 5. Clicking image to open Lightbox...")
    httpx.post(BRIDGE_URL, json={
        "action": "click",
        "params": {"selector": ".proj-att-img-preview"}
    }, timeout=10.0)
    time.sleep(1.5)

    # 6. Capture screenshot of open Lightbox Modal
    shot_lb = f"{SHOT_DIR}\\notes_lightbox_modal_verified.png"
    httpx.post(BRIDGE_URL, json={"action": "screenshot", "save_screenshot_path": shot_lb}, timeout=10.0)
    print("[+] Saved lightbox modal screenshot to:", shot_lb)

if __name__ == "__main__":
    run()
