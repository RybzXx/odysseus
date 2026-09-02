"""scripts/test_extensive_notes_parity.py"""
import httpx
import time
from pathlib import Path

BRIDGE_URL = "http://127.0.0.1:8765/api/action"
ODYSSEUS_URL = "http://127.0.0.1:7002"
SHOT_DIR = r"C:\Users\hmoha\.gemini\antigravity-cli\brain\e635a2da-caba-4f7b-935f-ca805b610af5"

def run():
    # 1. Create a dummy PNG image and dummy doc
    print("[*] 1. Creating sample test attachments...")
    img_path = Path("sample_preview.png")
    png_bytes = (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x01\x00\x00\x00\x00\x80'
        b'\x08\x02\x00\x00\x00\x97\xdb\x95e\x00\x00\x00\x19IDATx\x9cc\xfc\xff'
        b'\xff?\x03\x03\x03\x03\x03\x03\x03\x03\x03\x03\x03\x03\x00\x18\x06\x01'
        b'\x01\x18\xd7\xc0\xb0\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    img_path.write_bytes(png_bytes)

    # 2. Upload image via /api/upload
    print("[*] 2. Uploading image to /api/upload...")
    with open("sample_preview.png", "rb") as f:
        r_up = httpx.post(f"{ODYSSEUS_URL}/api/upload", files={"files": ("architecture_diagram.png", f, "image/png")}, timeout=10.0)
    print("Upload result:", r_up.status_code, r_up.json())
    up_item = r_up.json()["files"][0]
    att_img = {
        "id": up_item["id"],
        "filename": "architecture_diagram.png",
        "mime_type": "image/png",
        "size": len(png_bytes),
        "url": f"/api/upload/{up_item['id']}"
    }

    # 3. Create a project
    print("[*] 3. Creating / getting project...")
    r_proj = httpx.post(f"{ODYSSEUS_URL}/api/projects", json={
        "name": "Odysseus Deep Workspace",
        "description": "Comprehensive project management with rich notes and attachments",
        "priority": "critical"
    }, timeout=10.0)
    proj_id = r_proj.json()["project"]["id"]
    print(f"Project ID: {proj_id}")

    # 4. Create a rich Checklist note with color 'amber'
    print("[*] 4. Creating rich checklist note...")
    r_n1 = httpx.post(f"{ODYSSEUS_URL}/api/notes", json={
        "project_id": proj_id,
        "title": "Release Sprint Launch Tasks",
        "note_type": "checklist",
        "color": "amber",
        "pinned": True,
        "items": [
            {"text": "Design high-resolution attachment cards", "done": True},
            {"text": "Implement image lightbox modal with zoom & download", "done": True},
            {"text": "Add interactive document previewer iframe", "done": False},
            {"text": "Verify bidirectional PROJECT.md disk synchronization", "done": False}
        ]
    }, timeout=10.0)
    print("Checklist note created:", r_n1.status_code)

    # 5. Create a rich Text Note with viewable image attachment
    print("[*] 5. Creating rich text note with viewable image...")
    r_n2 = httpx.post(f"{ODYSSEUS_URL}/api/notes", json={
        "project_id": proj_id,
        "title": "System Architecture & Specs",
        "content": "Modular hybrid SQLite + Markdown manifest engine with reactive live updates and cross-tool linking.",
        "note_type": "note",
        "color": "cyan",
        "pinned": False,
        "attachments": [att_img]
    }, timeout=10.0)
    print("Text note with image created:", r_n2.status_code)

    # 6. Navigate Brave to http://localhost:7002/
    print("[*] 6. Navigating Brave and opening Projects Hub...")
    httpx.post(BRIDGE_URL, json={
        "action": "cdp_command",
        "params": {"method": "Page.navigate", "params": {"url": "http://localhost:7002/"}}
    }, timeout=10.0)
    time.sleep(3.0)

    # Open Projects modal and select the project
    expr_open = f"""
    (async () => {{
        const mod = await import('/static/js/projects.js');
        window.projectsModule = mod;
        mod.openProjects();
        return {{ ok: true }};
    }})()
    """
    httpx.post(BRIDGE_URL, json={
        "action": "cdp_command",
        "params": {"method": "Runtime.evaluate", "params": {"expression": expr_open, "awaitPromise": True, "returnByValue": True}}
    }, timeout=10.0)
    time.sleep(2.0)

    # Switch to Notes tab
    httpx.post(BRIDGE_URL, json={
        "action": "cdp_command",
        "params": {"method": "Runtime.evaluate", "params": {
            "expression": "(() => { const tab = document.querySelector('[data-tab=\"tasks\"]'); if (tab) tab.click(); })()",
            "returnByValue": True
        }}
    }, timeout=10.0)
    time.sleep(2.0)

    # 7. Capture live screenshot of the extensive Notes & To-Dos view
    shot = f"{SHOT_DIR}\\notes_extensive_parity_verified.png"
    httpx.post(BRIDGE_URL, json={"action": "screenshot", "save_screenshot_path": shot}, timeout=10.0)
    print("[+] Verified extensive notes screenshot saved to:", shot)

if __name__ == "__main__":
    run()
