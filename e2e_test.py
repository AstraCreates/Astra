import httpx, json, sys, time

# Wait for backend to be ready
for _ in range(20):
    try:
        httpx.get("http://localhost:8000/health", timeout=2).raise_for_status()
        print("backend ready")
        break
    except Exception:
        time.sleep(1)

r = httpx.post("http://localhost:8000/goal", timeout=30, json={
    "founder_id": "test_founder",
    "instruction": "Draft a short NDA for AcmeCo",
    "constraints": {}
})
print("submit:", r.status_code, r.json())
session_id = r.json()["session_id"]

print(f"streaming {session_id}...")
sys.stdout.flush()

with httpx.stream("GET", f"http://localhost:8000/stream/{session_id}", timeout=300) as resp:
    for line in resp.iter_lines():
        if line.startswith("data:"):
            try:
                ev = json.loads(line[5:].strip())
                print(json.dumps(ev))
                sys.stdout.flush()
                if ev.get("type") in ("goal_done", "goal_error"):
                    break
            except Exception:
                print(line)
                sys.stdout.flush()
