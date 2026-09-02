"""scripts/test_image_lightbox_live.py"""
import httpx
import time

BRIDGE_URL = "http://127.0.0.1:8765/api/action"
SHOT_DIR = r"C:\Users\hmoha\.gemini\antigravity-cli\brain\e635a2da-caba-4f7b-935f-ca805b610af5"

def run():
    # 1. Scroll the projects modal body down to show the image card
    print("[*] 1. Scrolling down in projects modal...")
    httpx.post(BRIDGE_URL, json={
        "action": "cdp_command",
        "params": {"method": "Runtime.evaluate", "params": {
            "expression": "(() => { const b = document.getElementById('proj-body'); if (b) b.scrollTop = 320; })()",
            "returnByValue": True
        }}
    }, timeout=10.0)
    time.sleep(1.5)

    # 2. Capture screenshot of the image note card
    shot1 = f"{SHOT_DIR}\\notes_with_image_card.png"
    httpx.post(BRIDGE_URL, json={"action": "screenshot", "save_screenshot_path": shot1}, timeout=10.0)
    print("[+] Screenshot with image card saved to:", shot1)

    # 3. Click the image to trigger Lightbox Modal
    print("[*] 3. Clicking image attachment to open Lightbox...")
    httpx.post(BRIDGE_URL, json={
        "action": "cdp_command",
        "params": {"method": "Runtime.evaluate", "params": {
            "expression": "(() => { const img = document.querySelector('.proj-att-img-preview'); if (img) { img.click(); return { clicked: true }; } return { clicked: false }; })()",
            "returnByValue": True
        }}
    }, timeout=10.0)
    time.sleep(1.5)

    # 4. Capture screenshot of the Lightbox Modal
    shot2 = f"{SHOT_DIR}\\notes_lightbox_modal_verified.png"
    httpx.post(BRIDGE_URL, json={"action": "screenshot", "save_screenshot_path": shot2}, timeout=10.0)
    print("[+] Verified lightbox screenshot saved to:", shot2)

if __name__ == "__main__":
    run()
