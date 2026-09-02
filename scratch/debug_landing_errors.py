import httpx
import time

BRIDGE_URL = "http://127.0.0.1:8765/api/action"

def run():
    print("Evaluating JS to get errors...")
    expr = """
    (async () => {
        let text = [];
        const originalError = console.error;
        console.error = function(...args) {
            text.push("ERR: " + args.join(' '));
            originalError.apply(console, args);
        };
        const mod = window.projectsModule;
        if (!mod) return "No projectsModule";
        try {
            mod._loadProjectDetail(null);
            text.push("_loadProjectDetail(null) called.");
            text.push("Current Project ID: " + mod._currentProjectId);
        } catch(e) {
            text.push("EXCEPTION: " + e.toString());
        }
        return text.join('\\n');
    })()
    """
    res = httpx.post(BRIDGE_URL, json={
        "action": "cdp_command",
        "params": {"method": "Runtime.evaluate", "params": {"expression": expr, "awaitPromise": True, "returnByValue": True}}
    }, timeout=10.0).json()
    print("JS RESULT:", res.get('result', {}).get('result', {}).get('value'))

if __name__ == "__main__":
    run()
