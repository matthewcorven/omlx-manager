#!/usr/bin/env python3
"""PUT a settings patch and print the reload-relevant response fields."""
import json, sys, urllib.error, urllib.request

OMLX = "http://127.0.0.1:8001"
MODEL = "Ornith-1.0-35B-oQ4e"

patch = json.loads(sys.argv[1])
req = urllib.request.Request(
    f"{OMLX}/admin/api/models/{MODEL}/settings",
    data=json.dumps(patch).encode(),
    headers={"Content-Type": "application/json"}, method="PUT")
try:
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.load(r)
except urllib.error.HTTPError as e:
    print(f"HTTP {e.code}: {e.read().decode()[:600]}")
    sys.exit(1)
print(json.dumps({k: d.get(k) for k in
                  ("success", "requires_reload", "auto_unloaded",
                   "auto_reloaded", "reload_deferred")}, indent=1))
