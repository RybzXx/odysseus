"""scripts/create_notes_todo.py

Opens Notes panel, enters 'work on gemini' as a todo, saves it, and captures screenshot.
"""

import httpx
import time

BRIDGE_URL = "http://127.0.0.1:8765/api/action"
SHOT_PATH = r"C:\Users\hmoha\.gemini\antigravity-cli\brain\e635a2da-caba-4f7b-935f-ca805b610af5\notes_todo_final_verified.png"

def run_test():
    # 1. Close any open modal and open Notes
    js_open_notes = """
    (() => {
        // Close projects modal if open
        const projModal = document.getElementById('projects-modal');
        if (projModal) projModal.style.display = 'none';

        // Open notes
        const notesBtn = document.getElementById('tool-notes-btn');
        if (notesBtn) notesBtn.click();
        return { ok: true };
    })()
    """

    print("[*] Opening Notes panel...")
    httpx.post(BRIDGE_URL, json={
        "action": "cdp_command",
        "params": {"method": "Runtime.evaluate", "params": {"expression": js_open_notes, "returnByValue": True}}
    }, timeout=10.0)

    time.sleep(1.5)

    # 2. Add todo with caption 'work on gemini'
    js_create_todo = """
    (() => {
        // Click 'Add a to-do...' input
        const todoInp = document.querySelector("input[placeholder*='to-do'], input[placeholder*='Add a to-do']");
        if (todoInp) {
            todoInp.focus();
            todoInp.value = "work on gemini";
            todoInp.dispatchEvent(new Event('input', { bubbles: true }));
            todoInp.dispatchEvent(new Event('change', { bubbles: true }));
        }

        // Click the Save button in the composer
        const saveBtns = Array.from(document.querySelectorAll("button, .btn"));
        const saveBtn = saveBtns.find(b => b.textContent.trim().includes('Save') && b.offsetParent !== null);
        if (saveBtn) {
            saveBtn.click();
            return { success: true, saved: true };
        }

        return { success: true, filled: !!todoInp };
    })()
    """

    print("[*] Creating todo 'work on gemini'...")
    r = httpx.post(BRIDGE_URL, json={
        "action": "cdp_command",
        "params": {"method": "Runtime.evaluate", "params": {"expression": js_create_todo, "returnByValue": True}}
    }, timeout=10.0)
    print("[+] Step result:", r.json())

    time.sleep(2.0)

    # Click save again if composer is open
    js_save_confirm = """
    (() => {
        const btns = Array.from(document.querySelectorAll("button, .btn, [role='button']"));
        const saveBtn = btns.find(b => b.textContent.trim().includes('Save') && b.offsetParent !== null);
        if (saveBtn) {
            saveBtn.click();
            return { clickedSave: true };
        }
        return { clickedSave: false };
    })()
    """
    httpx.post(BRIDGE_URL, json={
        "action": "cdp_command",
        "params": {"method": "Runtime.evaluate", "params": {"expression": js_save_confirm, "returnByValue": True}}
    }, timeout=10.0)

    time.sleep(2.0)

    # 3. Capture screenshot
    print(f"[*] Capturing final screenshot to {SHOT_PATH}...")
    s = httpx.post(BRIDGE_URL, json={
        "action": "screenshot",
        "save_screenshot_path": SHOT_PATH
    }, timeout=10.0)
    print(f"[+] Screenshot captured: {s.status_code}")

if __name__ == "__main__":
    run_test()
