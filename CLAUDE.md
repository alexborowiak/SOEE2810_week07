# Pond Rescue

A one-page classroom coding challenge for SOEE2810 (2nd-year environmental science). Students write Python in the browser to look after fish ponds with one aerator motor, across 7 levels that build up to the full challenge. Their code runs in the browser with Pyodide (from the jsDelivr CDN), and the page replays the run hour by hour, highlighting the line that's running.

## Files
- `pond_engine.py`: the simulation, the student functions `pollution()`, `motor_temp()`, `motor_on()`, `motor_off()`, `switch_to()` and `wait()`, the infinite-loop guards, and `LEVELS` (each level's scenario numbers, story, starter code, answer, hint, questions and goal check). `run_level(level_id, code)` runs the code on every test case of a level and returns JSON: a frame per hour, a log of every call and print with its line number, events, and pass/fail with a message.
- `page_template.html`: the page (level picker, brief, editor, playback, animation, chart, function guide). `%%LEVELS%%` and `%%ENGINE%%` are filled in by build.py.
- `build.py`: writes `index.html`, the single file GitHub Pages serves.
- `check_scenario.py`: runs every level's answer (must pass), its starter code, and the classic mistakes (must fail the expected way).

## Rules for changes
- Edit `pond_engine.py` and `page_template.html`, never `index.html` directly. Then run `python build.py`.
- After changing any level, message or number in `pond_engine.py`, run `python check_scenario.py`. Every line must say `ok`.
- Level 7 is tuned so its answer only just survives (peak pollution about 7.7, fish die above 8). Levels 1 to 6 are tuned so each level's answer passes and the previous level's code fails for the reason the level teaches.
- The answers the page reveals are the `answer` fields in `LEVELS`; check_scenario.py tests those exact strings. If a level's questions quote numbers from a run (levels 1, 2 and 7 do), re-check them after changing that level's scenario.
- Keep the student-facing function names, the function guide in the page (`FN_INFO`) and the engine in sync.
- Text is British English and plain: the students are environmental scientists, not programmers.
