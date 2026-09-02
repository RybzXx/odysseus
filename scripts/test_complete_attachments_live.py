"""scripts/test_complete_attachments_live.py"""
import httpx
import time
from pathlib import Path

ODYSSEUS_URL = "http://127.0.0.1:7002"
BRIDGE_URL = "http://127.0.0.1:8765/api/action"
SHOT_DIR = r"C:\Users\hmoha\.gemini\antigravity-cli\brain\e635a2da-caba-4f7b-935f-ca805b610af5"

def run():
    # 1. Fetch current project
    r_projs = httpx.get(f"{ODYSSEUS_URL}/api/projects", timeout=10.0)
    projs = r_projs.json()["projects"]
    deep_proj = next((p for p in projs if "Deep Workspace" in p["name"]), projs[0])
    proj_id = deep_proj["id"]
    print(f"Targeting Project: {deep_proj['name']} ({proj_id})")

    # 2. Upload test image (PNG)
    png_bytes = (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x01\x80\x00\x00\x00\xc0'
        b'\x08\x02\x00\x00\x00I4\xad\xaa\x00\x00\x00\x19IDATx\x9cc\xfc\xff'
        b'\xff?\x03\x03\x03\x03\x03\x03\x03\x03\x03\x03\x03\x03\x00\x18\x06\x01'
        b'\x01\x18\xd7\xc0\xb0\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    with open("architecture_preview.png", "wb") as f:
        f.write(png_bytes)

    with open("architecture_preview.png", "rb") as f:
        r_up1 = httpx.post(f"{ODYSSEUS_URL}/api/upload", files={"files": ("architecture_diagram.png", f, "image/png")}, timeout=10.0)
    
    file_item1 = r_up1.json()["files"][0]
    att_image = {
        "id": file_item1["id"],
        "filename": "architecture_diagram.png",
        "mime_type": "image/png",
        "size": len(png_bytes),
        "url": f"/api/upload/{file_item1['id']}"
    }

    # 3. Upload test document (Spec.md)
    doc_text = "# System Specification\n\n- Hybrid Project Spec\n- Parity with Google Keep & Odysseus Standalone Notes\n- Image Lightbox & Document Viewer"
    with open("spec.md", "w", encoding="utf-8") as f:
        f.write(doc_text)

    with open("spec.md", "rb") as f:
        r_up2 = httpx.post(f"{ODYSSEUS_URL}/api/upload", files={"files": ("specification.md", f, "text/markdown")}, timeout=10.0)
    
    file_item2 = r_up2.json()["files"][0]
    att_doc = {
        "id": file_item2["id"],
        "filename": "specification.md",
        "mime_type": "text/markdown",
        "size": len(doc_text.encode('utf-8')),
        "url": f"/api/upload/{file_item2['id']}"
    }

    # 4. Create Note with both attachments
    r_n = httpx.post(f"{ODYSSEUS_URL}/api/notes", json={
        "project_id": proj_id,
        "title": "System Architecture & Documentation",
        "content": "Full architecture overview with attached specification and system diagram.",
        "note_type": "note",
        "color": "cyan",
        "pinned": False,
        "attachments": [att_image, att_doc]
    }, timeout=10.0)
    print("Created Note with attachments:", r_n.status_code)

    # 5. Navigate to http://localhost:7002/projects
    print("[*] 5. Navigating to http://localhost:7002/projects ...")
    httpx.post(BRIDGE_URL, json={
        "action": "navigate",
        "params": {"url": "http://localhost:7002/projects"}
    }, timeout=10.0)
    time.sleep(3.5)

    # Switch to Notes tab
    httpx.post(BRIDGE_URL, json={
        "action": "click",
        "params": {"selector": '[data-tab="tasks"]'}
    }, timeout=10.0)
    time.sleep(2.0)

    # 6. Capture screenshot with image preview and document chip
    shot1 = f"{SHOT_DIR}\\notes_with_viewable_attachments_verified.png"
    httpx.post(BRIDGE_URL, json={"action": "screenshot", "save_screenshot_path": shot1}, timeout=10.0)
    print("[+] Saved notes with viewable attachments to:", shot1)

    # 7. Click image to open Lightbox
    print("[*] 7. Clicking image thumbnail to open Lightbox...")
    httpx.post(BRIDGE_URL, json={
        "action": "click",
        "params": {"selector": ".proj-att-img-preview"}
    }, timeout=10.0)
    time.sleep(1.5)

    # 8. Capture Lightbox screenshot
    shot2 = f"{SHOT_DIR}\\notes_lightbox_modal_verified.png"
    httpx.post(BRIDGE_URL, json={"action": "screenshot", "save_screenshot_path": shot2}, timeout=10.0)
    print("[+] Saved Lightbox screenshot to:", shot2)

    # Close Lightbox
    httpx.post(BRIDGE_URL, json={
        "action": "click",
        "params": {"selector": "#lightbox-close-btn"}
    }, timeout=10.0)
    time.sleep(1.0)

    # 9. Click Document chip to open Document Viewer
    print("[*] 9. Clicking document chip to open Document Viewer...")
    httpx.post(BRIDGE_URL, json={
        "action": "click",
        "params": {"selector": ".proj-att-file-chip"}
    }, timeout=10.0)
    time.sleep(1.5)

    # 10. Capture Document Viewer screenshot
    shot3 = f"{SHOT_DIR}\\notes_doc_viewer_modal_verified.png"
    httpx.post(BRIDGE_URL, json={"action": "screenshot", "save_screenshot_path": shot3}, timeout=10.0)
    print("[+] Saved Document Viewer screenshot to:", shot3)

if __name__ == "__main__":
    run()
