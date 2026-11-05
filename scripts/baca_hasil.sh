#!/usr/bin/env bash
# baca_hasil.sh -- cetak hasil job jambatan (fail respons GitHub Contents API).
set -e
F="${1:-hasil.json}"
python3 - "$F" <<'PY'
import base64
import json
import sys

doc = json.load(open(sys.argv[1], encoding="utf-8"))
res = json.loads(base64.b64decode(doc["content"]).decode("utf-8", "replace"))
print("exit:", res.get("exit"), "| secs:", res.get("secs"), "| who:", res.get("who"))
print((res.get("out") or "")[-2000:])
err = (res.get("err") or "").strip()
if err:
    print("ERR:", err[-600:])
PY
