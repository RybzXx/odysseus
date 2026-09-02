"""scripts/test_real_image_lightbox.py"""
import httpx
import time
from PIL import Image, ImageDraw, ImageFont

ODYSSEUS_URL = "http://127.0.0.1:7002"
BRIDGE_URL = "http://127.0.0.1:8765/api/action"
SHOT_DIR = r"C:\Users\hmoha\.gemini\antigravity-cli\brain\e635a2da-caba-4f7b-935f-ca805b610af5"

def run():
    # 1. Create a beautiful real graphic PNG
    im = Image.new('RGB', (600, 320), color=(20, 28, 45))
    draw = ImageDraw.Draw(im)
    draw.rectangle([(20, 20), (580, 300)], outline=(232, 163, 61), width=3)
    draw.rectangle([(50, 60), (250, 180)], fill=(34, 45, 75), outline=(74, 144, 226), width=2)
    draw.rectangle([(350, 60), (550, 180)], fill=(34, 45, 75), outline=(46, 204, 113), width=2)
    draw.line([(250, 120), (350, 120)], fill=(232, 163, 61), width=3)
    draw.text((70, 110), "SQLite Store", fill=(255, 255, 255))
    draw.text((370, 110), "PROJECT.md", fill=(255, 255, 255))
    draw.text((160, 240), "Odysseus Living Spec Hub", fill=(232, 163, 61))
    im.save("system_architecture.png")

    # 2. Upload image to /api/upload
    with open("system_architecture.png", "rb") as f:
        r_up = httpx.post(f"{ODYSSEUS_URL}/api/upload", files={"files": ("system_architecture.png", f, "image/png")}, timeout=10.0)
    
    file_item = r_up.json()["files"][0]
    att_image = {
        "id": file_item["id"],
        "filename": "system_architecture.png",
        "mime_type": "image/png",
        "size": file_item["size"],
        "url": f"/api/upload/{file_item['id']}"
    }

    # 3. Create Note with the graphic attachment
    r_projs = httpx.get(f"{ODYSSEUS_URL}/api/projects", timeout=10.0)
    proj_id = r_projs.json()["projects"][0]["id"]

    r_n = httpx.post(f"{ODYSSEUS_URL}/api/notes", json={
        "project_id": proj_id,
        "title": "System Architecture Diagram",
        "content": "Visual map of the hybrid SQLite + PROJECT.md storage engine.",
        "note_type": "note",
        "color": "cyan",
        "pinned": True,
        "attachments": [att_image]
    }, timeout=10.0)
    print("Created Note with real image:", r_n.status_code)

    # 4. Refresh projects in Brave
    print("[*] 4. Navigating to http://localhost:7002/projects ...")
    httpx.post(BRIDGE_URL, json={
        "action": "navigate",
        "params": {"url": "http://localhost:7002/projects"}
    }, timeout=10.0)
    time.sleep(3.0)

    # Switch to Notes tab
    httpx.post(BRIDGE_URL, json={
        "action": "click",
        "params": {"selector": '[data-tab="tasks"]'}
    }, timeout=10.0)
    time.sleep(2.0)

    # 5. Capture screenshot of the card with the rendered image thumbnail
    shot1 = f"{SHOT_DIR}\\notes_with_real_image_verified.png"
    httpx.post(BRIDGE_URL, json={"action": "screenshot", "save_screenshot_path": shot1}, timeout=10.0)
    print("[+] Saved notes card with real image to:", shot1)

    # 6. Click image thumbnail to open Lightbox
    print("[*] 6. Clicking image thumbnail to open Lightbox...")
    httpx.post(BRIDGE_URL, json={
        "action": "click",
        "params": {"selector": ".proj-att-img-preview"}
    }, timeout=10.0)
    time.sleep(1.5)

    # 7. Capture screenshot of open Lightbox Modal
    shot2 = f"{SHOT_DIR}\\notes_lightbox_modal_verified.png"
    httpx.post(BRIDGE_URL, json={"action": "screenshot", "save_screenshot_path": shot2}, timeout=10.0)
    print("[+] Saved open Lightbox screenshot to:", shot2)

if __name__ == "__main__":
    run()
