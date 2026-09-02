import httpx

BRIDGE_URL = "http://127.0.0.1:9222/bridge"
res = httpx.post(BRIDGE_URL, json={
    "action": "cdp_command",
    "params": {"method": "Runtime.evaluate", "params": {
        "expression": "(async () => { const mod = await import('/static/js/projects.js'); window.projectsModule = mod; mod.openProjects(); return 'done'; })()",
        "awaitPromise": True,
        "returnByValue": True
    }}
})
print(res.json())
