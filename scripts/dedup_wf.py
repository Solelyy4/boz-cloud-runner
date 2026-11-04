"""dedup_wf.py — buang baris pendua dalam workflow telegram.yml."""
import pathlib
import re

p = pathlib.Path(".github/workflows/telegram.yml")
s = p.read_text(encoding="utf-8")
baris = "          python -c \"import hermes_agent; print('hermes_agent', getattr(hermes_agent,'__version__','?'))\" 2>/dev/null || true\n"
n_sebelum = s.count("import hermes_agent")
# kekalkan hanya satu kejadian
if n_sebelum > 1:
    first = s.find(baris)
    if first != -1:
        head = s[:first + len(baris)]
        tail = s[first + len(baris):].replace(baris, "")
        s = head + tail
p.write_text(s, encoding="utf-8")
print("sebelum:", n_sebelum, "| selepas:", s.count("import hermes_agent"))
print("'Connected to Telegram' comment masih ada:", "no-build-isolation" in s)
