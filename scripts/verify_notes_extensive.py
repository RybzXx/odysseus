"""scripts/verify_notes_extensive.py"""
import httpx
import time

BRIDGE_URL = "http://127.0.0.1:8765/api/action"
SHOT_DIR = r"C:\Users\hmoha\.gemini\antigravity-cli\brain\e635a2da-caba-4f7b-935f-ca805b610af5"

def run():
    # 1. Select Deep Workspace and scroll down
    js = """
    (() => {
        const select = document.getElementById('proj-select');
        if (select) {
            const opt = Array.from(select.options).find(o => o.text.includes('Deep Workspace'));
            if (opt) {
                select.value = opt.value;
                select.dispatchEvent(new Event('change', { bubbles: true }));
            }
        }
        setTimeout(() => {
            const tab = document.querySelector('[data-tab="tasks"]');
            if (tab) tab.click();
            setTimeout(() => {
                const body = document.getElementById('proj-body');
                if (body) body.scrollTop = 220;
            }, 600);
        }, 600);
        return { triggered: true };
    })()
    """
    res = httpx.post(BRIDGE_URL, json={
        "action": "eval_js",
        "params": {"code": js}
    }, timeout=10.0)
    print("Eval result:", res.json())
    time.sleep(2.5)

    # 2. Capture screenshot of the extensive notes grid
    shot = f"{SHOT_DIR}\\notes_extensive_parity_verified.png"
    httpx.post(BRIDGE_URL, json={"action": "screenshot", "save_screenshot_path": shot}, timeout=10.0)
    print("[+] Saved notes screenshot to:", shot)

    # 3. Click image to trigger Lightbox Modal
    js_click_img = """
    (() => {
        const img = document.querySelector('.proj-att-img-preview');
        if (img) {
            img.click();
            return { clicked: true };
        }
        return { clicked: false };
    })()
    """
    httpx.post(BRIDGE_URL, json={
        "action": "eval_js",
        "params": {"code": js_click_img}
    }, timeout=10.0)
    time.sleep(1.5)

    # 4. Capture screenshot of the open Lightbox Modal
    shot_lb = f"{SHOT_DIR}\\notes_lightbox_modal_verified.png"
    httpx.post(BRIDGE_URL, json={"action": "screenshot", "save_screenshot_path": shot_lb}, timeout=10.0)
    print("[+] Saved lightbox modal screenshot to:", shot_lb)

if __name__ == "__main__":
    run()
