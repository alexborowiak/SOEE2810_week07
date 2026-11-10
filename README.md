# Pond Rescue

SOEE2810, week 7 practical. Students learn Python by running a fish farm's aerator: 18 short questions, each one a bit of code they write, run, and watch play out hour by hour, with the line that's running lit up as it goes. The last question is the full challenge.

**Play it:** https://alexborowiak.github.io/SOEE2810_week07/

Nothing to install. Python runs in the browser with [Pyodide](https://pyodide.org), loaded from the jsDelivr CDN (about 10 MB the first time, so students need internet access). Each student's code and progress are saved in their own browser.

## The questions

| # | Question | Python |
|---|---|---|
| 1 | How far below the safe limit (3) is pond 1? (two test mornings) | calling a function, sums |
| 2 | Is it getting worse? Print the change over 3 hours | variables |
| 3 | Four readings, 3 hours apart | `for` loops |
| 4 | Highest and average of a day's readings | lists, `max`, `sum`, `len` |
| 5 | Switch the motor on if the pond is above 3 (three test mornings, one exactly 3.0) | `if` |
| 6 | The motor is running: switch it off if the pond is 3 or below | `if`, `<=` |
| 7 | Print danger, warning or ok | `elif` |
| 8 | All clear only if both ponds are 3 or below | `and` |
| 9 | Alarm if either pond is above 6 | `or` |
| 10 | Move the hose to the dirtier pond | comparing values |
| 11 | Wait for the storm, then switch on | `while` |
| 12 | Keep the motor on until the pond is clean | `while` |
| 13 | Keep watch through two days of storms | `while True` |
| 14 | Switch on only if the pond is dirty and the motor is cool | `and` |
| 15 | Stop the motor overheating | nested loops |
| 16 | Write `report(pond)` | `def` |
| 17 | Write `clean(pond)` for two ponds | functions and loops |
| 18 | Pond Rescue: 4 days, 3 storms, a toxic spill. Bonus: fewest motor hours | everything |

Each question says what to achieve, not how: the starter code is blank (except question 15, where fixing the given code is the point), and the pond functions it needs are listed with it as short bullets (`pollution(x)` reads pollution of pond x, `wait(x)` waits x hours), because calling those isn't the Python skill. Each question is checked automatically, some against more than one test case so hard-coding doesn't pass, with a specific message for each classic mistake: the motor catches fire, a pond is left too early, the hose is moved with the motor running (the farmer gets soaked), a loop has no `wait()` (time stops), or a typo (with "Did you mean...?"). The `and`/`or` questions explain each result in True/False terms, e.g. "pond 1 <= 3 is False, pond 2 <= 3 is True. False and True gives False".

The animation builds up with the questions: question 1 is just a pond and its sensor, and the clock, storm drain, aerator, second pond, movable hose and thermometer each appear when a question first needs them, with a "NEW" sticker.

## Seeing what the code does

After Run, the page replays the run:

- The line that's running is highlighted in the editor: blue for a quick call, amber while `wait()` or `switch_to()` lets time pass.
- The variables panel, beside the output, shows every variable's value at that moment and highlights what just changed (e.g. `i = 2`, was 1), including a function's own variables while it runs. Step (→) goes one line at a time.
- Each call pops up beside what it touches in the animation, e.g. `pollution(1) → 4.2` at the pond's sensor.
- The reading card above each pond shows only what the code has measured: "?" until `pollution()` is called, then the last reading. When the sensor is read, its light flashes and the reading travels up to the card. (The water colour and the chart still show the real pollution.)
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
- Progress lives in each browser's local storage (under `pondrescue-18.`; saved work started afresh when the question numbers last moved), so it doesn't follow a student between PCs. Their code is easy to copy out of the editor if they want to keep it.
