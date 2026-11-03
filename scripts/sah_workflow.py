"""sah_workflow.py — pengesah struktur workflow tanpa pyyaml."""
import pathlib
import re

FAIL = ".github/workflows"
FILES = ["telegram.yml", "evolve.yml", "autolearn.yml", "selfupgrade.yml",
         "ensure-cloud.yml", "selftest.yml", "tgprobe.yml"]

for f in FILES:
    p = pathlib.Path(FAIL) / f
    if not p.exists():
        print(f"{f:20s} TIADA")
        continue
    s = p.read_text(encoding="utf-8")
    ok = all(k in s for k in ("name:", "on:", "jobs:"))
    cron = re.findall(r'cron: "([^"]+)"', s)
    print(f"{f:20s} struktur={'OK' if ok else 'ROS'} cron={cron}")

t = (pathlib.Path(FAIL) / "telegram.yml").read_text(encoding="utf-8")
print("\ntelegram.yml:")
for k in ("rm -f home/.skills_prompt_snapshot.json", "jumlah skill:", "auto_load: semua skill dipetik ADA",
          "git add -f status.log", "status-tmp", "force_ipv4"):
    print(f"  {'ADA  ' if k in t else 'TIADA'} {k}")

e = (pathlib.Path(FAIL) / "evolve.yml").read_text(encoding="utf-8")
print("\nevolve.yml:")
for k in ("scripts_evolve.py", "BOZ_PAT", "*/10 * * * *", "push ok", "timeout-minutes"):
    print(f"  {'ADA  ' if k in e else 'TIADA'} {k}")
