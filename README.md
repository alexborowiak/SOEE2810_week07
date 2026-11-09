# Pond Rescue

SOEE2810, week 7 practical. Students learn Python by running a fish farm's aerator: they write the code, press Run, and watch it play out hour by hour, with the line that's running lit up as it goes. Seven short levels build up to the full challenge.

**Play it:** https://alexborowiak.github.io/SOEE2810_week07/

Nothing to install. Python runs in the browser with [Pyodide](https://pyodide.org), loaded from the jsDelivr CDN (about 10 MB the first time, so students need internet access). Each student's code and progress are saved in their own browser.

## The levels

| Level | New Python | The task |
|---|---|---|
| 1. Test the water | calling functions, variables, `print()` | Read the pond sensor twice, 3 hours apart, and print the change |
| 2. Sensor log | `for` loops, lists, `max()`, `sum()`, `len()` | Log a reading every 3 hours through a storm; print the highest and the average |
| 3. Switch it on | `if` / `else`, comparisons | Motor on only if pollution is above 3. Tested on three mornings, one of them exactly 3.0 |
| 4. Keep watch | `while` loops | On/off control through two days of storm overflows |
| 5. Too hot | nested loops | A long storm: let the motor cool down so it doesn't catch fire |
| 6. Two ponds | `def`, parameters | Write `clean(pond)` and use it to look after both ponds |
| 7. Pond Rescue | all of it | Four days, three storm overflows and a toxic spill. Bonus: fewest motor hours |

Every level has a short story, the task, a Python reminder, questions to think about, a hint and an answer. The code is checked automatically, with a specific message for each classic mistake: the motor catches fire, a pond is left too early, the hose is moved with the motor running (the farmer gets soaked), a loop has no `wait()` (time stops), or a typo (with "Did you mean...?").

## Seeing what the code does

After Run, the page replays the run:

- The line that's running is highlighted in the editor: blue for a quick call, amber while `wait()` or `switch_to()` lets time pass.
- Each call pops up beside what it touches in the animation, e.g. `pollution(1) → 4.2` at the pond's sensor.
- The output log lists every print and every function call, with the pond time and line number. Click a line to jump there.
- Pause, step one line at a time (→), scrub, change speed, or click the chart to jump to a moment. The chart marks the readings the code actually took, so students can compare them with the real pollution line.

## Answers

Each level has a small "Show answer" link next to the hint. It opens the answer blurred until the student clicks "I've had a go: show me", along with answers to that level's questions. The answers are in the page source (it's a static page), so a determined student can find them.

## Files

- `pond_engine.py`: the simulation, the student functions and the levels. Each level's story, starter code, answer, hint, questions and scenario numbers are in `LEVELS` at the bottom.
- `page_template.html`: the page (level picker, editor, playback, animation, chart, function guide).
- `build.py`: puts the engine and the level text into the template and writes `index.html`.
- `check_scenario.py`: runs every level's answer (must pass) and the classic mistakes (must fail the expected way).
- `index.html`: the built page that GitHub Pages serves. Don't edit it by hand.

## Changing it

Edit `pond_engine.py` or `page_template.html`, then:

```bash
python check_scenario.py
```

```bash
python build.py
```

Every line of the check should say `ok`. Then commit and push, and GitHub Pages updates within a minute or two.

## Publishing (once)

On GitHub: **Settings → Pages → Build and deployment → Source: Deploy from a branch → Branch: `main`, folder `/ (root)` → Save.**

## Notes

- The page respects the "reduce motion" setting: calmer animation and no shaking or confetti. To force the full animation, for example on a projector PC with that setting on, add `?motion=full` to the address.
- Progress lives in each browser's local storage, so it doesn't follow a student between PCs. Their code is easy to copy out of the editor if they want to keep it.
