"""scripts/test_direct_projects_route.py"""
import httpx
import time

BRIDGE_URL = "http://127.0.0.1:8765/api/action"
SHOT_DIR = r"C:\Users\hmoha\.gemini\antigravity-cli\brain\e635a2da-caba-4f7b-935f-ca805b610af5"

def run():
    # 1. Navigate directly to http://localhost:7002/projects
    print("[*] 1. Navigating to http://localhost:7002/projects ...")
    httpx.post(BRIDGE_URL, json={
        "action": "navigate",
        "params": {"url": "http://localhost:7002/projects"}
    }, timeout=10.0)
    time.sleep(3.5)

    # 2. Click Notes & To-Dos Tab (tab index 2)
    print("[*] 2. Clicking Notes & To-Dos tab...")
    httpx.post(BRIDGE_URL, json={
        "action": "click",
        "params": {"selector": '[data-tab="tasks"]'}
    }, timeout=10.0)
    time.sleep(2.0)

    # 3. Take screenshot of the extensive Notes view
    shot1 = f"{SHOT_DIR}\\notes_extensive_parity_verified.png"
    httpx.post(BRIDGE_URL, json={"action": "screenshot", "save_screenshot_path": shot1}, timeout=10.0)
    print("[+] Saved extensive notes screenshot to:", shot1)

    # 4. Scroll down slightly
    print("[*] 4. Scrolling down...")
    httpx.post(BRIDGE_URL, json={
        "action": "scroll",
        "params": {"selector": "#proj-body", "y": 280}
    }, timeout=10.0)
    time.sleep(1.5)

    # 5. Click the image to trigger Lightbox Modal
    print("[*] 5. Clicking image to open Lightbox...")
    httpx.post(BRIDGE_URL, json={
        "action": "click",
        "params": {"selector": ".proj-att-img-preview"}
    }, timeout=10.0)
    time.sleep(1.5)

    # 6. Capture screenshot of open Lightbox Modal
    shot2 = f"{SHOT_DIR}\\notes_lightbox_modal_verified.png"
    httpx.post(BRIDGE_URL, json={"action": "screenshot", "save_screenshot_path": shot2}, timeout=10.0)
    print("[+] Saved lightbox screenshot to:", shot2)

if __name__ == "__main__":
    run()
