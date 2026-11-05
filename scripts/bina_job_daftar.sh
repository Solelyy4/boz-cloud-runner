#!/usr/bin/env bash
# bina_job_daftar.sh -- cetak JSON job untuk mendaftarkan perkhidmatan jambatan di laptop.
# Dipisahkan daripada workflow supaya blok inline Python tidak memecahkan YAML.
set -e
ID="${1:?id job diperlukan}"
python3 - "$ID" <<'PY'
import json
import sys

job = {
    "id": sys.argv[1],
    "cmd": "& 'C:/Users/zahin/AppData/Local/hermes/bin/register_service_task.ps1'",
    "cwd": "C:/Users/zahin/AppData/Local/hermes/bin",
    "timeout": 240,
    "reply": True,
}
print(json.dumps(job))
PY
