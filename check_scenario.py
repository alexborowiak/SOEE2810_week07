"""Checks the pond scenario still works: the model answers win, the classic mistakes fail.

Run:  python check_scenario.py
Exit code is 1 if anything is off, so rerun this after changing any numbers in pond_engine.py.
"""
import json
import sys
import pond_engine as E

STRATS = {
"nothing": """
while True:
    wait()
""",
"model": """
while True:
    for pond in [1, 2]:
        switch_to(pond)
        while pollution(pond) > 3:
            if motor_temp() > 50:
                motor_off()
                while motor_temp() > 20:
                    wait()
            else:
                motor_on()
                wait()
        motor_off()
""",
"model_wait": """
while True:
    for pond in [1, 2]:
        switch_to(pond)
        while pollution(pond) > 3:
            if motor_temp() > 50:
                motor_off()
                while motor_temp() > 20:
                    wait()
            else:
                motor_on()
                wait()
        motor_off()
    wait()
""",
"no_cooldown": """
while True:
    for pond in [1, 2]:
        motor_off()
        switch_to(pond)
        while pollution(pond) > 3:
            motor_on()
            wait()
    wait()
""",
"hot80": """
while True:
    for pond in [1, 2]:
        switch_to(pond)
        while pollution(pond) > 3:
            if motor_temp() > 80:
                motor_off()
                while motor_temp() > 20:
                    wait()
            else:
                motor_on()
                wait()
        motor_off()
    wait()
""",
"pond1_only": """
switch_to(1)
while True:
    if motor_temp() > 50:
        motor_off()
        while motor_temp() > 20:
            wait()
    elif pollution(1) > 3:
        motor_on()
        wait()
    else:
        motor_off()
        wait()
""",
"if_not_while": """
while True:
    for pond in [1, 2]:
        switch_to(pond)
        if pollution(pond) > 3:
            if motor_temp() > 50:
                motor_off()
                while motor_temp() > 20:
                    wait()
            else:
                motor_on()
                wait()
        motor_off()
    wait()
""",
"no_motor_off": """
while True:
    for pond in [1, 2]:
        switch_to(pond)
        while pollution(pond) > 3:
            if motor_temp() > 50:
                motor_off()
                while motor_temp() > 20:
                    wait()
            else:
                motor_on()
                wait()
    wait()
""",
"starter": """
while True:
    if pollution(1) > 3:
        switch_to(1)
        motor_on()
    else:
        motor_off()
    wait()
""",
"frozen": """
while True:
    if pollution(1) > 3:
        motor_on()
""",
"cool_short": """
while True:
    for pond in [1, 2]:
        switch_to(pond)
        while pollution(pond) > 3:
            if motor_temp() > 50:
                motor_off()
                wait()
            else:
                motor_on()
                wait()
        motor_off()
    wait()
""",
"leave_at5": """
while True:
    for pond in [1, 2]:
        switch_to(pond)
        while pollution(pond) > 5:
            if motor_temp() > 50:
                motor_off()
                while motor_temp() > 20:
                    wait()
            else:
                motor_on()
                wait()
        motor_off()
""",
"leave_after_cool": """
while True:
    for pond in [1, 2]:
        switch_to(pond)
        if pollution(pond) > 3:
            while motor_temp() > 20:
                wait()
            motor_on()
            wait()
            motor_off()
""",
"error": """
while True:
    if polution(1) > 3:
        motor_on()
    wait()
""",
}

MUST_WIN = ["model", "model_wait"]
EXPECTED = {
    "nothing": "lose", "no_cooldown": "lose", "hot80": "lose", "pond1_only": "lose",
    "if_not_while": "lose", "cool_short": "lose", "leave_at5": "lose", "leave_after_cool": "lose",
    "starter": "lose", "no_motor_off": "sprayed", "frozen": "frozen", "error": "error",
}


def main():
    bad = 0
    for name, code in STRATS.items():
        out = json.loads(E.run_user_code(code))
        r, f = out["result"], out["frames"]
        want = "win" if name in MUST_WIN else EXPECTED.get(name)
        ok = want is None or r["outcome"] == want
        bad += not ok
        peak = max(max(x["p1"], x["p2"]) for x in f)
        print(f"{'ok ' if ok else 'BAD'} {name:17s} {r['outcome']:8s} (want {want}) motor_hours={r['motor_hours']:3d} peak={peak:4.1f}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
