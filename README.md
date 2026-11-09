# Pond Rescue

SOEE2810, week 7 practical. Students write Python in the browser to keep two fish ponds clean with one aerator motor, and watch an animation of what their code actually does: the loops, the waits, the motor heating up and the ponds filling with sewage.

**Play it:** https://alexborowiak.github.io/SOEE2810_week07/

Nothing to install. Python runs in the browser with [Pyodide](https://pyodide.org) (loaded from the jsDelivr CDN, so students need internet access). Code is saved in the student's own browser between visits.

## The challenge

Two ponds, one motor, four days of sewage spills and a toxic barrel. Students call:

| Function | What it does |
|---|---|
| `pollution(pond)` | Pollution in pond 1 or 2. Safe below 3, fish die above 8. |
| `motor_temp()` | Motor temperature in °C. Catches fire at 100. |
| `motor_on()` / `motor_off()` | Start or stop the aerator. Heats ~15°C/hour, cools ~8°C/hour. |
| `switch_to(pond)` | Move the air hose. Takes 3 hours. Motor must be off. |
| `wait()` | Let 3 hours pass (`wait(6)`, `wait(9)`… for longer). |

The starter code only looks after pond 1. To keep every fish alive they need a `for` loop over both ponds, a `while` loop to stay with a polluted pond until it is safe, and another `while` loop to let the motor cool down. The scenario is tuned so a good answer only just survives.

Classic mistakes each get their own failure: the motor catches fire, a pond is left too early and the toxic leak creeps past 8, the hose is swapped with the motor running (the farmer gets soaked), or a loop with no `wait()` stops time.

## Files

- `pond_engine.py`: the simulation, scenario numbers and the student functions.
- `page_template.html`: the page (animation, editor, function guide).
- `build.py`: puts the engine inside the template and writes `index.html`.
- `check_scenario.py`: runs a model answer and the classic mistakes through the engine.
- `index.html`: the built page that GitHub Pages serves. Don't edit it by hand.

## Changing it

```bash
python check_scenario.py   # every line should say ok
python build.py            # rewrites index.html
```

Then commit and push, and GitHub Pages updates within a minute or two.

## Publishing (once)

On GitHub: **Settings → Pages → Build and deployment → Source: Deploy from a branch → Branch: `main`, folder `/ (root)` → Save.**
