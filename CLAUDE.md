# Pond Rescue

A one-page classroom coding challenge. Students write Python in the browser to keep two fish ponds clean with one aerator motor. Their code runs in the browser with Pyodide, which loads from the jsDelivr CDN.

## Files
- `pond_engine.py`: the simulation, scenario settings (spills, toxic barrel, motor heat) and the student functions `pollution()`, `motor_temp()`, `motor_on()`, `motor_off()`, `switch_to()` and `wait()`. It also guards against infinite loops and returns frames and events as JSON.
- `page_template.html`: the page (animation, editor, function guide). `%%ENGINE%%` is where the engine gets inserted.
- `build.py`: writes `index.html` (a single file you can host anywhere, e.g. GitHub Pages).
- `check_scenario.py`: runs the model answer and the classic mistakes through the engine.

## Rules for changes
- Edit `pond_engine.py` and `page_template.html`, never `index.html` directly. Then run `python build.py`.
- The scenario is tuned so the model answer only just survives (peak pollution about 7.7, fish die above 8). After changing any number in `pond_engine.py`, run `python check_scenario.py`. Every line must say `ok`.
- Keep the student-facing function names and the function guide in the page in sync with the engine.
