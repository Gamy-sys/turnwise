"""Live API test: fetch a transcript, edit a token, PUT it, confirm re-render."""
import json
import urllib.request

BASE = "http://127.0.0.1:8010"


def get(path):
    with urllib.request.urlopen(BASE + path) as r:
        return json.load(r)


def put(path, body):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="PUT")
    with urllib.request.urlopen(req) as r:
        return json.load(r)


projects = get("/api/projects")
done = [p for p in projects if p["state"] == "done"]
assert done, "no completed project to test"
pid = done[0]["project_id"]
print("testing project", pid)

tr = get(f"/api/projects/{pid}/transcript")
first_tok = tr["turns"][0]["tokens"][0]
print("before:", first_tok["text"], "| cues:", [c["type"] for c in first_tok["cues"]])

# Edit: change text + add a user cutoff cue.
first_tok["text"] = "SOEDIT"
first_tok["cues"].append({"type": "cutoff", "symbol": "-", "source": "user",
                          "confidence": 1.0, "evidence": {}})

res = put(f"/api/projects/{pid}/transcript", tr)
assert res["ok"], res
jeff = res["transcript"]["jefferson"]
print("after re-render, first line:", jeff.splitlines()[0])
# text edit is reflected and the user-added cutoff hyphen is present.
assert "SOEDI" in jeff, "text edit not reflected in render"
assert "T-" in jeff, "user cutoff not reflected in render"

# reload to confirm persistence
tr2 = get(f"/api/projects/{pid}/transcript")
assert tr2["turns"][0]["tokens"][0]["text"] == "SOEDIT"
print("PERSISTED OK")
print("\nEDIT ROUND-TRIP PASSED")
