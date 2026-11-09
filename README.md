# Pond Rescue

SOEE2810, week 7 practical. Students learn Python by running a fish farm's aerator: 14 short questions, each one a bit of code they write, run, and watch play out hour by hour, with the line that's running lit up as it goes. The last question is the full challenge.

**Play it:** https://alexborowiak.github.io/SOEE2810_week07/

Nothing to install. Python runs in the browser with [Pyodide](https://pyodide.org), loaded from the jsDelivr CDN (about 10 MB the first time, so students need internet access). Each student's code and progress are saved in their own browser.

## The questions

| # | Question | Python |
|---|---|---|
| 1 | Read the sensor and print it | calling a function |
| 2 | Is it getting worse? Print the change over 3 hours | variables |
| 3 | Four readings, 3 hours apart | `for` loops |
| 4 | Highest and average of a day's readings | lists, `max`, `sum`, `len` |
| 5 | Switch the motor on if the pond is above 3 (three test mornings, one exactly 3.0) | `if` |
| 6 | Print danger, warning or ok | `elif` |
| 7 | Move the hose to the dirtier pond | comparing values |
| 8 | Wait for the storm, then switch on | `while` |
| 9 | Keep the motor on until the pond is clean | `while` |
| 10 | Keep watch through two days of storms | `while True` |
| 11 | Stop the motor overheating | nested loops |
| 12 | Write `report(pond)` | `def` |
| 13 | Write `clean(pond)` for two ponds | functions and loops |
| 14 | Pond Rescue: 4 days, 3 storms, a toxic spill. Bonus: fewest motor hours | everything |

Each question is checked automatically, some against more than one test case so hard-coding doesn't pass, with a specific message for each classic mistake: the motor catches fire, a pond is left too early, the hose is moved with the motor running (the farmer gets soaked), a loop has no `wait()` (time stops), or a typo (with "Did you mean...?").

## Seeing what the code does

After Run, the page replays the run:

- The line that's running is highlighted in the editor: blue for a quick call, amber while `wait()` or `switch_to()` lets time pass.
- Each call pops up beside what it touches in the animation, e.g. `pollution(1) → 4.2` at the pond's sensor.
- The output log lists every print and every function call, with the pond time and line number. Click a line to jump there.
- Pause, step one line at a time (→), scrub, change speed, or click the chart to jump to a moment. The chart marks the readings the code actually took, so students can compare them with the real pollution line.

## Answers

Each question has a small "Answer" link next to the hint. It opens the answer blurred until the student clicks "I've had a go: show me". The answers are in the page source (it's a static page), so a determined student can find them.

## Files

- `pond_engine.py`: the simulation, the student functions and the questions. Each question's task, starter code, hint, answer, test cases and check are in `LEVELS` at the bottom.
- `page_template.html`: the page (question picker, editor, playback, animation, chart, function guide).
- `build.py`: puts the engine and the question text into the template and writes `index.html`.
- `check_scenario.py`: runs every question's answer (must pass) and the classic mistakes (must fail the expected way).
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
