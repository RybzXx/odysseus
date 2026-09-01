"""scripts/fast_research_scan.py
Fast scanner to extract real technical facts, stack info, and structural context across all 21 projects.
"""
import os
import json
from pathlib import Path

ROOT = Path(r"D:\ai_projects_2026")
IGNORES = {
    ".git", "node_modules", "venv", ".venv", "__pycache__", ".next",
    "dist", "build", ".dart_tool", ".gradle", "ios", "android", "data", "windows", "linux", "web"
}

results = []

for item in sorted(ROOT.iterdir()):
    if not item.is_dir() or item.name.startswith("."):
        continue
    
    files = []
    top_entries = []
    stack_signals = []
    
    # 1. Top-level files and folders
    for entry in item.iterdir():
        if entry.name in IGNORES:
            continue
        top_entries.append(entry.name + ("/" if entry.is_dir() else ""))
        if entry.is_file():
            files.append(entry.name)
            
    # 2. Key configuration checks
    pkg_json = item / "package.json"
    req_txt = item / "requirements.txt"
    pyproj = item / "pyproject.toml"
    pubspec = item / "pubspec.yaml"
    cargo = item / "Cargo.toml"
    dockerfile = item / "Dockerfile"
    
    tech_details = {}
    
    if pkg_json.exists():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8", errors="ignore"))
            tech_details["npm_name"] = data.get("name")
            tech_details["dependencies"] = list(data.get("dependencies", {}).keys())[:10]
            tech_details["scripts"] = list(data.get("scripts", {}).keys())
            stack_signals.append("Node.js/JavaScript/TypeScript")
            if "next" in data.get("dependencies", {}): stack_signals.append("Next.js")
            if "react" in data.get("dependencies", {}): stack_signals.append("React")
            if "vue" in data.get("dependencies", {}): stack_signals.append("Vue")
            if "tailwindcss" in data.get("dependencies", {}) or "tailwindcss" in data.get("devDependencies", {}): stack_signals.append("Tailwind CSS")
        except Exception:
            pass
            
    if req_txt.exists():
        try:
            lines = [l.strip() for l in req_txt.read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip() and not l.startswith("#")]
            tech_details["python_packages"] = lines[:10]
            stack_signals.append("Python")
            if any("fastapi" in l.lower() for l in lines): stack_signals.append("FastAPI")
            if any("flask" in l.lower() for l in lines): stack_signals.append("Flask")
            if any("django" in l.lower() for l in lines): stack_signals.append("Django")
            if any("streamlit" in l.lower() for l in lines): stack_signals.append("Streamlit")
            if any("pandas" in l.lower() for l in lines): stack_signals.append("Pandas/Data")
        except Exception:
            pass
            
    if pubspec.exists():
        try:
            lines = pubspec.read_text(encoding="utf-8", errors="ignore").splitlines()
            stack_signals.append("Flutter/Dart")
        except Exception:
            pass
            
    # Check for python files directly
    py_files = list(item.glob("*.py"))
    if py_files and "Python" not in stack_signals:
        stack_signals.append("Python")
        
    # Check for HTML/JS
    html_files = list(item.glob("*.html"))
    if html_files and not stack_signals:
        stack_signals.append("Static Web (HTML/CSS/JS)")

    # Read PROJECT.md executive summary if exists
    manifest = item / "PROJECT.md"
    manifest_excerpt = ""
    if manifest.exists():
        text = manifest.read_text(encoding="utf-8", errors="ignore")
        manifest_excerpt = text[:300]
        
    results.append({
        "folder": item.name,
        "stack": list(set(stack_signals)) or ["Custom/Data"],
        "top_entries": sorted(top_entries)[:15],
        "details": tech_details,
        "manifest_excerpt": manifest_excerpt
    })

print(json.dumps(results, indent=2))
