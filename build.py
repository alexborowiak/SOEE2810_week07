"""Builds the single-file page: puts pond_engine.py and the level text inside page_template.html."""
import json

import pond_engine

# utf-8 explicitly: the files contain °C, → etc. and Windows defaults to cp1252
eng = open("pond_engine.py", encoding="utf-8").read()
assert "</script" not in eng
levels = json.dumps([pond_engine.level_for_page(lv) for lv in pond_engine.LEVELS]).replace("</", "<\\/")
html = open("page_template.html", encoding="utf-8").read()
html = html.replace("%%LEVELS%%", levels).replace("%%ENGINE%%", eng)
open("index.html", "w", encoding="utf-8", newline="\n").write(html)
print(f"wrote index.html ({len(pond_engine.LEVELS)} levels)")
