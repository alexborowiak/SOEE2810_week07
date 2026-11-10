"""Checks every question still works: each question's answer (the one the page reveals) passes, its starter
code fails, and the classic mistakes fail the way they should. Question 19, the final challenge, is tuned so
its answer only just survives (peak pollution about 7.7).

Run:  python check_scenario.py
Exit code is 1 if anything is off, so rerun this after changing any numbers in pond_engine.py.
"""
import json
import sys
import pond_engine as E

LEVEL = {lv["id"]: lv for lv in E.LEVELS}
ANSWER, STARTER = "<answer>", "<starter>"

COOLDOWN = """
while True:
    if pollution(1) > 3:
        if motor_temp() > 50:
            motor_off()
            while motor_temp() > 20:
                wait()
        else:
            motor_on()
            wait()
    else:
        motor_off()
        wait()
"""

# question -> [(name, code, expected)]. expected is the outcome, or one outcome per test case.
CHECKS = {
    1: [
        ("answer", ANSWER, "win"),
        ("starter", STARTER, "lose"),
        ("no_print", "x = 3 - pollution(1)\n", "lose"),
        ("print_reading", "print(pollution(1))\n", "lose"),
        ("backwards", "print(pollution(1) - 3)\n", "lose"),
        ("hard_coded", "x = pollution(1)\nprint(0.5)\n", ("win", "lose")),
    ],
    2: [
        ("answer", ANSWER, "win"),
        ("starter", STARTER, "lose"),
        ("no_change", "a = pollution(1)\nprint(a)\nwait()\nb = pollution(1)\nprint(b)\n", "lose"),
        ("no_wait", "a = pollution(1)\nb = pollution(1)\nprint(b - a)\n", "lose"),
    ],
    3: [
        ("answer", ANSWER, "win"),
        ("starter", STARTER, "lose"),
        ("no_wait", "for i in range(4):\n    print(pollution(1))\n", "lose"),
        ("no_print", "for i in range(4):\n    x = pollution(1)\n    wait()\n", "lose"),
        ("wait_5", "for i in range(4):\n    print(pollution(1))\n    wait(5)\n", "win"),
        ("wait_zero", "for i in range(4):\n    print(pollution(1))\n    wait(0)\n", "lose"),
    ],
    4: [
        ("answer", ANSWER, "win"),
        ("starter", STARTER, "lose"),
        ("no_list", "for i in range(4):\n    print(pollution(1))\n    wait(3)\n", "lose"),
        ("print_in_loop", "readings = []\nfor i in range(4):\n    readings.append(pollution(1))\n    print(readings)\n    wait(3)\n", "win"),
        ("one_reading", "readings = [pollution(1)]\nprint(readings)\n", "lose"),
    ],
    5: [
        ("answer", ANSWER, "win"),
        ("starter", STARTER, "lose"),
        ("list_only", "r = []\nfor i in range(8):\n    r.append(pollution(1))\n    wait()\nprint(r)\n", "lose"),
        ("no_wait", "r = []\nfor i in range(8):\n    r.append(pollution(1))\nprint(max(r))\nprint(sum(r) / len(r))\n", "lose"),
    ],
    6: [
        ("answer", ANSWER, ("win", "win", "win")),
        ("starter", STARTER, ("lose", "win", "win")),
        ("always_on", "motor_on()\n", ("win", "lose", "lose")),
        ("greater_eq", "if pollution(1) >= 3:\n    motor_on()\n", ("win", "win", "lose")),
    ],
    7: [
        ("answer", ANSWER, ("win", "win", "win")),
        ("starter", STARTER, ("lose", "win", "lose")),
        ("less_than", "if pollution(1) < 3:\n    motor_off()\n", ("win", "win", "lose")),
        ("always_off", "motor_off()\n", ("win", "lose", "win")),
        ("wrong_way", "if pollution(1) > 3:\n    motor_off()\n", ("lose", "lose", "lose")),
    ],
    8: [
        ("answer", ANSWER, ("win", "win", "win")),
        ("starter", STARTER, ("lose", "lose", "lose")),
        ("wrong_order", 'level = pollution(1)\nif level > 3:\n    print("warning")\nelif level > 6:\n    print("danger")\nelse:\n    print("ok")\n', ("lose", "win", "win")),
        ("two_ifs", 'level = pollution(1)\nif level > 6:\n    print("danger")\nif level > 3:\n    print("warning")\nelse:\n    print("ok")\n', ("lose", "win", "win")),
    ],
    9: [
        ("answer", ANSWER, ("win", "win", "win")),
        ("starter", STARTER, ("lose", "lose", "lose")),
        ("or_not_and", 'if pollution(1) <= 3 or pollution(2) <= 3:\n    print("all clear")\nelse:\n    print("check ponds")\n', ("win", "lose", "lose")),
        ("half_compare", 'if pollution(1) and pollution(2) <= 3:\n    print("all clear")\nelse:\n    print("check ponds")\n', ("win", "win", "lose")),
        ("pond1_only", 'if pollution(1) <= 3:\n    print("all clear")\nelse:\n    print("check ponds")\n', ("win", "lose", "win")),
    ],
    10: [
        ("answer", ANSWER, ("win", "win", "win")),
        ("starter", STARTER, ("lose", "lose", "lose")),
        ("and_not_or", 'if pollution(1) > 6 and pollution(2) > 6:\n    print("alarm")\nelse:\n    print("fine")\n', ("lose", "lose", "win")),
        ("pond1_only", 'if pollution(1) > 6:\n    print("alarm")\nelse:\n    print("fine")\n', ("win", "lose", "win")),
    ],
    11: [
        ("answer", ANSWER, ("win", "win")),
        ("starter", STARTER, ("lose", "lose")),
        ("always_pond2", "switch_to(2)\nmotor_on()\n", ("lose", "win")),
        ("never_switch", "motor_on()\n", ("win", "lose")),
    ],
    12: [
        ("answer", ANSWER, ("win", "win")),
        ("starter", STARTER, ("lose", "lose")),
        ("hard_coded", "wait(15)\nmotor_on()\n", ("win", "lose")),
        ("hourly", "while pollution(1) <= 3:\n    wait(1)\nmotor_on()\n", ("win", "win")),
        ("zero_wait_loop", "while pollution(1) <= 3:\n    wait(0)\nmotor_on()\n", ("frozen", "frozen")),
        ("if_not_while", "if pollution(1) <= 3:\n    wait()\nmotor_on()\n", ("lose", "lose")),
        ("no_wait", "while pollution(1) <= 3:\n    pass\nmotor_on()\n", ("frozen", "frozen")),
    ],
    13: [
        ("answer", ANSWER, ("win", "win")),
        ("starter", STARTER, ("lose", "win")),
        ("hard_coded", "motor_on()\nwait()\nmotor_off()\n", ("win", "lose")),
        ("check_after", "motor_on()\nwait()\nwhile pollution(1) > 3:\n    wait()\nmotor_off()\n", ("win", "lose")),
    ],
    14: [
        ("answer", ANSWER, "win"),
        ("starter", STARTER, "lose"),
        ("never_off", "while True:\n    if pollution(1) > 3:\n        motor_on()\n    wait()\n", "lose"),
        ("always_on", "motor_on()\nwhile True:\n    wait()\n", "lose"),
        ("no_loop", "if pollution(1) > 3:\n    motor_on()\n", "lose"),
        ("no_wait", "while True:\n    if pollution(1) > 3:\n        motor_on()\n", "frozen"),
    ],
    15: [
        ("answer", ANSWER, ("win", "win", "win")),
        ("starter", STARTER, ("lose", "win", "win")),
        ("or_not_and", "if pollution(1) > 3 or motor_temp() < 50:\n    motor_on()\n", ("win", "lose", "lose")),
        ("no_temp", "if pollution(1) > 3:\n    motor_on()\n", ("win", "lose", "win")),
    ],
    16: [
        ("answer", ANSWER, "win"),
        ("starter", STARTER, "lose"),
        ("q14_code", LEVEL[14]["answer"], "lose"),
        ("hot70", COOLDOWN.replace("> 50", "> 70"), "lose"),
        ("nothing", "while True:\n    wait()\n", "lose"),
    ],
    17: [
        ("answer", ANSWER, "win"),
        ("starter", STARTER, "lose"),
        ("pond1_inside", "def report(pond):\n    print(pollution(1))\n\nreport(1)\nreport(2)\n", "lose"),
        ("one_call", "def report(pond):\n    print(pollution(pond))\n\nreport(1)\n", "lose"),
        ("no_function", "print(pollution(1))\nprint(pollution(2))\n", "lose"),
    ],
    18: [
        ("answer", ANSWER, "win"),
        ("starter", STARTER, "lose"),
        ("pond1_only", COOLDOWN, "lose"),
        ("no_function", LEVEL[19]["answer"], "lose"),
        ("no_motor_off", LEVEL[18]["answer"].replace("    motor_off()\n\nwhile", "\nwhile"), "sprayed"),
    ],
    19: [
        ("answer", ANSWER, "win"),
        ("starter", STARTER, "lose"),
        ("nothing", "\nwhile True:\n    wait()\n", "lose"),
        ("model_wait", """
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
""", "win"),
        ("q18_answer", LEVEL[18]["answer"], "win"),
        ("no_cooldown", """
while True:
    for pond in [1, 2]:
        motor_off()
        switch_to(pond)
        while pollution(pond) > 3:
            motor_on()
            wait()
    wait()
""", "lose"),
        ("hot80", """
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
""", "lose"),
        ("pond1_only", """
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
""", "lose"),
        ("if_not_while", """
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
""", "lose"),
        ("no_motor_off", """
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
""", "sprayed"),
        ("frozen", """
while True:
    if pollution(1) > 3:
        motor_on()
""", "frozen"),
        ("cool_short", """
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
""", "lose"),
        ("leave_at5", """
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
""", "lose"),
        ("leave_after_cool", """
while True:
    for pond in [1, 2]:
        switch_to(pond)
        if pollution(pond) > 3:
            while motor_temp() > 20:
                wait()
            motor_on()
            wait()
            motor_off()
""", "lose"),
        ("error", """
while True:
    if polution(1) > 3:
        motor_on()
    wait()
""", "error"),
        ("typo", "while True\n    wait()\n", "error"),
    ],
}


def main():
    bad = 0
    for level_id, checks in CHECKS.items():
        for name, code, want in checks:
            code = {ANSWER: LEVEL[level_id]["answer"], STARTER: LEVEL[level_id]["starter"]}.get(code, code)
            out = json.loads(E.run_level(level_id, code))
            got = tuple(c["result"]["outcome"] for c in out["cases"])
            if isinstance(want, str):
                got = got[0] if len(got) == 1 else ("win" if out["passed"] else next(g for g in got if g != "win"))
            ok = got == want
            if name == "answer":
                ok = ok and out["passed"]
            bad += not ok
            hours = sum(c["result"]["motor_hours"] for c in out["cases"])
            peak = max(max(f[f"p{p}"] for p in range(1, c["ponds"] + 1)) for c in out["cases"] for f in c["frames"])
            show = lambda x: x if isinstance(x, str) else ",".join(x)
            print(f"{'ok ' if ok else 'BAD'} Q{level_id:<2} {name:16s} {show(got):15s} (want {show(want)}) "
                  f"motor_hours={hours:3d} peak={peak:4.1f}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
