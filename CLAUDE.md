# Pond Rescue

A one-page classroom coding challenge for SOEE2810 (2nd-year environmental science). Students write Python in the browser to look after fish ponds with one aerator motor, across 17 short interactive questions that build up to the full challenge. Their code runs in the browser with Pyodide (from the jsDelivr CDN), and the page replays the run hour by hour, highlighting the line that's running.

## Files
- `pond_engine.py`: the simulation, the student functions `pollution()`, `motor_temp()`, `motor_on()`, `motor_off()`, `switch_to()` and `wait()`, the infinite-loop guards, and `LEVELS` (each question's task, starter code, hint, answer, test-case scenarios and goal check). `run_level(level_id, code)` runs the code on every test case of a question and returns JSON: a frame per hour, a log of every call and print with its line number, events, and pass/fail with a message.
- `page_template.html`: the page (question picker, question, editor, playback, animation, chart, function guide). `%%LEVELS%%` and `%%ENGINE%%` are filled in by build.py.
- `build.py`: writes `index.html`, the single file GitHub Pages serves.
- `check_scenario.py`: runs every question's answer (must pass), its starter code (must fail), and the classic mistakes (must fail the expected way).

## Rules for changes
- Edit `pond_engine.py` and `page_template.html`, never `index.html` directly. Then run `python build.py`.
- After changing any question, message or number in `pond_engine.py`, run `python check_scenario.py`. Every line must say `ok`.
- Question 17 is tuned so its answer only just survives (peak pollution about 7.7, fish die above 8). Questions with several test cases use them so hard-coded answers fail.
- The answers the page reveals are the `answer` fields in `LEVELS`; check_scenario.py tests those exact strings.
- Keep the student-facing function names, the function guide in the page (`FN_INFO`) and the engine in sync.
- Keep the page simple: one question at a time, short task text, no extra panels. The animation only draws what a question uses (`partsOf()` in the page, from each question's `uses` and `storm`); keep its flat, ink-outlined style and don't add detail. Text is British English and plain: the students are environmental scientists, not programmers.
