"""Builds the single-file page: puts pond_engine.py inside page_template.html."""
# utf-8 explicitly: the files contain °C, → etc. and Windows defaults to cp1252
eng = open("pond_engine.py", encoding="utf-8").read()
assert "</script" not in eng
html = open("page_template.html", encoding="utf-8").read().replace("%%ENGINE%%", eng)
open("index.html", "w", encoding="utf-8", newline="\n").write(html)
print("wrote index.html")
