"""scripts/test_select_deep_workspace.py"""
import httpx
import time

BRIDGE_URL = "http://127.0.0.1:8765/api/action"
SHOT_DIR = r"C:\Users\hmoha\.gemini\antigravity-cli\brain\e635a2da-caba-4f7b-935f-ca805b610af5"

def run():
    # 1. Select the Odysseus Deep Workspace project in the dropdown
    print("[*] 1. Selecting Odysseus Deep Workspace...")
    expr_sel = """
    (() => {
        const select = document.getElementById('proj-select');
        if (select) {
            const opt = Array.from(select.options).find(o => o.text.includes('Deep Workspace'));
            if (opt) {
                select.value = opt.value;
                select.dispatchEvent(new Event('change', { bubbles: true }));
                return { selected: opt.text, id: opt.value };
            }
        }
        return { selected: false };
    })()
    """
    res_sel = httpx.post(BRIDGE_URL, json={
        "action": "cdp_command",
        "params": {"method": "Runtime.evaluate", "params": {"expression": expr_sel, "returnByValue": True}}
    }, timeout=10.0)
    print("Select result:", res_sel.json())
    time.sleep(2.0)

    # 2. Scroll down to show the image card and checklist card
    print("[*] 2. Scrolling down in modal body...")
    httpx.post(BRIDGE_URL, json={
        "action": "cdp_command",
        "params": {"method": "Runtime.evaluate", "params": {
            "expression": "(() => { const b = document.getElementById('proj-body'); if (b) b.scrollTop = 280; })()",
            "returnByValue": True
        }}
    }, timeout=10.0)
    time.sleep(1.5)

    # 3. Capture screenshot showing both the checklist card AND the cyan image note card
    shot1 = f"{SHOT_DIR}\\notes_deep_workspace_cards.png"
    httpx.post(BRIDGE_URL, json={"action": "screenshot", "save_screenshot_path": shot1}, timeout=10.0)
    print("[+] Saved cards screenshot to:", shot1)

    # 4. Click image to trigger the Lightbox Modal
    print("[*] 4. Clicking image to open Lightbox...")
    httpx.post(BRIDGE_URL, json={
        "action": "cdp_command",
        "params": {"method": "Runtime.evaluate", "params": {
            "expression": "(() => { const img = document.querySelector('.proj-att-img-preview'); if (img) { img.click(); return { clicked: true }; } return { clicked: false }; })()",
            "returnByValue": True
        }}
    }, timeout=10.0)
    time.sleep(1.5)

    # 5. Capture screenshot of the open Lightbox Modal
    shot2 = f"{SHOT_DIR}\\notes_lightbox_modal_verified.png"
    httpx.post(BRIDGE_URL, json={"action": "screenshot", "save_screenshot_path": shot2}, timeout=10.0)
    print("[+] Saved lightbox modal screenshot to:", shot2)

if __name__ == "__main__":
    run()
