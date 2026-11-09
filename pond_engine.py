"""Pond Rescue: the simulation behind the page.

Students write Python that calls pollution(), motor_temp(), motor_on(), motor_off(), switch_to() and
wait(). run_level(level_id, code) runs their code against every test case of a level and returns JSON:
a frame for every hour (for the animation), a log of every call and print with its line number (so the
page can highlight the line that is running), events, and whether the level's goal was met.

The levels are in LEVELS at the bottom: scenario numbers, story, starter code, answer, hint and
questions. build.py copies the text into the page; check_scenario.py checks every answer still passes.
"""
import difflib
import json
import math
import re
import sys

# ---------------- physics: the same in every level ----------------
AMBIENT = 15.0        # motor cools down to this
START_TEMP = 20.0
HEAT_PER_HOUR = 15.0  # motor running
COOL_PER_HOUR = 8.0   # motor off
FIRE_TEMP = 100.0
SAFE = 3.0            # 3 or below is safe
DEADLY = 8.0          # above 8 the fish die
AERATE = 1.5          # pollution removed per hour by a running aerator
SWITCH_HOURS = 3      # swapping the air hose to the other pond takes this long
SENSOR_HOURS = 3      # the sensors update every 3 hours, so wait() works in steps of 3
DECAY = 0.03          # natural clean-up per hour (fraction)
BASE_INFLOW = 0.045   # background pollution per hour
START_CLOCK = 8       # every run starts at 08:00 on day 1

# ---------------- the final challenge (level 7) ----------------
# Tuned so the model answer only just survives (peak pollution about 7.7).
HOURS = 96            # 4 days
START_POLLUTION = {1: 1.5, 2: 1.5}
# spills: (centre hour, width in hours, total pollution added)
SPILLS = {
    1: [(18, 6, 12.0)],
    2: [(38, 5, 12.0), (62, 6, 8.0)],
}
# toxic spills: (hour, pond, instant jump, total that leaks out of the barrel afterwards, hours until the leak is worst)
TOXIC = [(52, 1, 1.5, 16.0, 8.0)]

USER_FILE = "<your code>"
LINE_LIMIT = 300000   # lines run without time passing before we call it an infinite loop
CALL_LIMIT = 20000    # the same for function calls
LOG_LIMIT = 4000      # calls and prints kept for the page
TICK_LOG_LIMIT = 60   # ... and at most this many in any one hour


def clock(t):
    h = START_CLOCK + int(t)
    return f"Day {h // 24 + 1}, {h % 24:02d}:00"


class Scenario:
    """One test case: how long it runs, how many ponds, and what pours into them."""

    def __init__(self, name="", hours=HOURS, ponds=2, start=None, spills=None, toxic=(),
                 base=BASE_INFLOW, after_code=None):
        self.name = name
        self.hours = hours
        self.ponds = tuple(range(1, ponds + 1))
        self.start = dict(start) if start else {p: 1.5 for p in self.ponds}
        self.spills = {p: list((spills or {}).get(p, [])) for p in self.ponds}
        self.toxic = list(toxic)
        self.base = dict(base) if isinstance(base, dict) else {p: base for p in self.ponds}
        # hours the ponds carry on once the student's code has finished (None: to the end)
        self.after_code = after_code

    def sewage(self, pond, t):
        total = self.base[pond]
        for c, s, a in self.spills[pond]:
            total += a / (s * math.sqrt(2 * math.pi)) * math.exp(-0.5 * ((t + 0.5 - c) / s) ** 2)
        return total

    def leak(self, pond, t):
        total = 0.0
        for h, p, jump, amount, tau in self.toxic:
            if p == pond and t >= h:
                x = t + 0.5 - h
                total += amount * x / tau ** 2 * math.exp(-x / tau)
        return total


class _Halt(BaseException):
    """Stops the student's code. A BaseException, so `except Exception:` in their code can't swallow it."""


class _SimOver(_Halt):
    pass


class _Sprayed(_Halt):
    pass


class _TimeFrozen(_Halt):
    pass


class PondError(Exception):
    """Mistakes in how the built-in functions are used."""


def _user_line():
    """Line number in the student's code that is running right now."""
    f = sys._getframe(1)
    while f is not None and f.f_code.co_filename != USER_FILE:
        f = f.f_back
    return f.f_lineno if f is not None else None


class Sim:
    def __init__(self, sc):
        self.sc = sc
        self.t = 0
        self.P = {p: float(sc.start[p]) for p in sc.ponds}
        self.temp = START_TEMP
        self.motor = False
        self.target = 1
        self.motor_dead = False
        self.fish_dead = {p: None for p in sc.ponds}
        self.motor_hours = 0
        self.switching = False
        self.ever_on = False
        self.halt = None
        self.frames = []
        self.events = []
        self.log = []          # every call and print, in order, for the page
        self.readings = []     # (hour, pond, value) for every pollution() call
        self.printed = []      # every printed line
        self.out = None
        self.lines_since_tick = 0
        self.calls_since_tick = 0
        self.logged_this_tick = 0
        self._snapshot()

    # ---- recording ----
    def _snapshot(self):
        f = {"t": self.t, "temp": round(self.temp, 2), "motor": self.motor, "target": self.target,
             "fire": self.motor_dead, "switching": self.switching}
        for p in self.sc.ponds:
            sewage = self.sc.sewage(p, self.t)
            f[f"p{p}"] = round(self.P[p], 3)
            f[f"dead{p}"] = self.fish_dead[p] is not None
            f[f"in{p}"] = round(sewage, 3)
            f[f"st{p}"] = round(sewage - self.sc.base[p], 3)   # the storm overflow part
            f[f"tx{p}"] = round(self.sc.leak(p, self.t), 3)
        self.frames.append(f)

    def _update_snapshot(self):
        # actions taken at the current hour change what the animation shows for it
        self.frames.pop()
        self._snapshot()

    def event(self, kind, text, pond=None):
        e = {"t": self.t, "kind": kind, "text": text}
        if pond is not None:
            e["pond"] = pond
        self.events.append(e)

    def log_call(self, fn, args="", ret=None, hours=0, note=None):
        if self.out is not None:
            self.out.flush()
        if len(self.log) >= LOG_LIMIT or self.logged_this_tick >= TICK_LOG_LIMIT:
            return
        self.logged_this_tick += 1
        entry = {"k": "call", "t": self.t, "line": _user_line(), "fn": fn, "args": args}
        if ret is not None:
            entry["ret"] = ret
        if hours:
            entry["hours"] = hours
        if note:
            entry["note"] = note
        self.log.append(entry)

    def log_print(self, text, line):
        text = text[:300]
        if len(self.printed) < 2000:
            self.printed.append(text)
        if len(self.log) < LOG_LIMIT:
            self.log.append({"k": "print", "t": self.t, "line": line, "text": text})

    # ---- physics ----
    def hour(self):
        running = self.motor and not self.motor_dead
        for h, p, jump, amount, tau in self.sc.toxic:
            if h == self.t:
                self.P[p] += jump
                self.event("toxic", f"Toxic spill! A barrel of chemicals fell into pond {p}.", p)
        for p in self.sc.ponds:
            aer = AERATE if (running and self.target == p) else 0.0
            inflow = self.sc.sewage(p, self.t) + self.sc.leak(p, self.t)
            self.P[p] = max(0.0, self.P[p] + inflow - DECAY * self.P[p] - aer)
        if running:
            self.temp += HEAT_PER_HOUR
            self.motor_hours += 1
        else:
            self.temp = max(AMBIENT, self.temp - COOL_PER_HOUR)
        self.t += 1
        for p in self.sc.ponds:
            if self.fish_dead[p] is None and self.P[p] > DEADLY:
                self.fish_dead[p] = self.t
                who = f"Pond {p}" if len(self.sc.ponds) > 1 else "The pond"
                self.event("fish", f"{who}: pollution passed {DEADLY:g}. The fish didn't make it.", p)
        if running and self.temp >= FIRE_TEMP:
            self.motor_dead = True
            self.motor = False
            self.event("fire", f"The motor hit {FIRE_TEMP:g}°C and caught fire!")
        self.lines_since_tick = 0
        self.calls_since_tick = 0
        self.logged_this_tick = 0
        self._snapshot()
        if self.t >= self.sc.hours:
            self.halt = _SimOver
            raise _SimOver()

    def tick_call(self):
        if self.halt is not None:
            raise self.halt()
        self.calls_since_tick += 1
        if self.calls_since_tick > CALL_LIMIT:
            self.halt = _TimeFrozen
            raise _TimeFrozen()


def make_builtins(sim):
    ponds = sim.sc.ponds

    def check_pond(pond, name):
        if isinstance(pond, bool) or not isinstance(pond, (int, float)) or pond not in ponds:
            if len(ponds) == 1:
                raise PondError(f"{name}({pond!r}): there's only one pond in this level, pond 1.")
            raise PondError(f"{name}({pond!r}): there are only ponds 1 and 2.")
        return int(pond)

    def pollution(pond):
        """Pollution in a pond. 3 or below is safe; above 8 the fish die."""
        pond = check_pond(pond, "pollution")
        sim.tick_call()
        value = round(sim.P[pond], 1)
        if len(sim.readings) < 5000:
            sim.readings.append((sim.t, pond, value))
        sim.log_call("pollution", repr(pond), value)
        return value

    def motor_temp():
        """Motor temperature in °C. It catches fire at 100."""
        sim.tick_call()
        value = round(sim.temp)
        sim.log_call("motor_temp", "", value)
        return value

    def motor_on():
        """Switch the motor on."""
        sim.tick_call()
        sim.log_call("motor_on")
        if sim.motor_dead:
            return
        sim.ever_on = True
        if not sim.motor:
            sim.motor = True
            sim._update_snapshot()

    def motor_off():
        """Switch the motor off."""
        sim.tick_call()
        sim.log_call("motor_off")
        if sim.motor:
            sim.motor = False
            sim._update_snapshot()

    def switch_to(pond):
        """Move the air hose to pond 1 or 2. Takes 3 hours. The motor must be off."""
        pond = check_pond(pond, "switch_to")
        sim.tick_call()
        if pond == sim.target:
            sim.log_call("switch_to", repr(pond), note="already there")
            return
        if sim.motor and not sim.motor_dead:
            sim.log_call("switch_to", repr(pond), note="motor still on!")
            sim.target = pond
            sim._update_snapshot()
            sim.event("spray", "You moved the air hose with the motor running. It whipped round and soaked the farmer!")
            sim.halt = _Sprayed
            raise _Sprayed()
        sim.log_call("switch_to", repr(pond), hours=SWITCH_HOURS)
        sim.target = pond
        sim.switching = True
        sim._update_snapshot()
        try:
            for i in range(SWITCH_HOURS):
                if i == SWITCH_HOURS - 1:
                    sim.switching = False
                sim.hour()
        finally:
            sim.switching = False

    def wait(hours=None):
        """Let time pass: 3 hours, or wait(6), wait(9)... The sensors only update every 3 hours."""
        shown = "" if hours is None else repr(hours)
        if hours is None:
            hours = SENSOR_HOURS
        if not isinstance(hours, int) or isinstance(hours, bool) or hours <= 0 or hours % SENSOR_HOURS:
            raise PondError(f"wait({hours!r}): the sensors only update every 3 hours, so use wait(), wait(6), wait(9)...")
        if sim.halt is not None:
            raise sim.halt()
        sim.log_call("wait", shown, hours=hours)
        for _ in range(hours):
            sim.hour()

    fns = {
        "pollution": pollution,
        "motor_temp": motor_temp,
        "motor_on": motor_on,
        "motor_off": motor_off,
        "switch_to": switch_to,
        "wait": wait,
    }
    for name, fn in fns.items():
        fn.__qualname__ = name   # so error messages say pollution(), not make_builtins.<locals>.pollution()
    return fns


class _PrintCatcher:
    def __init__(self, sim):
        self.sim = sim
        self.buf = ""
        self.line = None

    def write(self, s):
        s = str(s)
        if s and not self.buf:
            self.line = _user_line()
        self.buf += s
        while "\n" in self.buf:
            text, self.buf = self.buf.split("\n", 1)
            self.sim.log_print(text, self.line)
        return len(s)

    def flush(self):
        if self.buf:
            self.sim.log_print(self.buf, self.line)
            self.buf = ""


# ---------------- running a level ----------------
def _syntax_message(e):
    msg = e.msg
    if isinstance(e, IndentationError) or "indent" in msg:
        msg += " (check the spaces at the start of the line)"
    elif msg == "expected ':'":
        msg += " (if, else, while, for and def lines end with a colon)"
    elif "never closed" in msg or "unmatched" in msg:
        msg += " (check your brackets)"
    return f"{type(e).__name__}: {msg}"


COMMON_BUILTINS = ["print", "range", "len", "max", "min", "sum", "round", "abs", "int", "float", "str", "list",
                   "True", "False", "None"]


def _error_message(e, ns):
    text = f"{type(e).__name__}: {e}"
    name = getattr(e, "name", None)
    if isinstance(e, NameError) and name:
        # the student's own names and the built-ins they're likely to use (not eval, exec, ...)
        known = [k for k in ns if not k.startswith("_")] + COMMON_BUILTINS
        close = difflib.get_close_matches(name, known, n=1, cutoff=0.7)
        if close:
            text += f". Did you mean {close[0]}?"
    return text


def _error_line(exc):
    tb = exc.__traceback__
    line = None
    while tb is not None:
        if tb.tb_frame.f_code.co_filename == USER_FILE:
            line = tb.tb_lineno
        tb = tb.tb_next
    return line


def _run_case(level, sc, compiled):
    sim = Sim(sc)
    result = {"outcome": None, "error": None, "error_line": None}
    ns = {"__name__": "__main__"}
    ns.update(make_builtins(sim))
    called = {}   # the student's own functions -> how many times they were called

    def local_tracer(frame, event, arg):
        if event == "line":
            if sim.halt is not None:
                raise sim.halt()
            sim.lines_since_tick += 1
            if sim.lines_since_tick > LINE_LIMIT:
                sim.halt = _TimeFrozen
                raise _TimeFrozen()
        return local_tracer

    def global_tracer(frame, event, arg):
        if frame.f_code.co_filename == USER_FILE:
            name = frame.f_code.co_name
            if event == "call" and name != "<module>":
                called[name] = called.get(name, 0) + 1
            return local_tracer
        return None

    old_stdout = sys.stdout
    sim.out = _PrintCatcher(sim)
    sys.stdout = sim.out
    code_done = False
    try:
        sys.settrace(global_tracer)
        try:
            exec(compiled, ns)
            code_done = True
        finally:
            sys.settrace(None)
    except _SimOver:
        pass
    except _Sprayed:
        result["outcome"] = "sprayed"
    except _TimeFrozen:
        result["outcome"] = "frozen"
        result["error"] = ("Time stopped! Your code is going round a loop without ever calling wait(), "
                           "so no time passes. Add a wait() inside the loop.")
        sim.event("frozen", "Time stopped! No wait() in your loop.")
    except RecursionError as e:
        result["outcome"] = "error"
        result["error"] = "RecursionError: a function keeps calling itself."
        result["error_line"] = _error_line(e)
    except Exception as e:  # PondError and student mistakes: NameError, TypeError, ...
        result["outcome"] = "error"
        result["error"] = str(e) if isinstance(e, PondError) else _error_message(e, ns)
        result["error_line"] = _error_line(e)
    finally:
        sim.out.flush()
        sys.stdout = old_stdout
        sim.out = None

    result["code_done"] = code_done
    result["code_end"] = sim.t
    if code_done and sim.t < sc.hours:
        # the code finished early: the ponds carry on with the motor as it was left
        end = sc.hours if sc.after_code is None else min(sc.hours, sim.t + sc.after_code)
        sim.halt = None
        try:
            while sim.t < end:
                sim.hour()
        except _SimOver:
            pass
    if result["outcome"] == "error":
        sim.event("error", f"Your code crashed on line {result['error_line']}." if result["error_line"] else "Your code crashed.")
    _judge(level, sc, sim, result, ns, called)
    return _pack(sim, sc, result)


def _judge(level, sc, sim, result, ns, called):
    advice = level.get("advice", {})
    outcome = result["outcome"]
    passed = False
    if outcome == "error":
        line = result["error_line"]
        message = (f"Line {line}: " if line else "") + result["error"]
    elif outcome == "frozen":
        message = result["error"]
    elif outcome == "sprayed":
        message = (f"On {clock(sim.t)} you moved the hose with the motor still running. It whipped round "
                   "and soaked the farmer. Call motor_off() before switch_to().")
    else:
        dead = [p for p in sc.ponds if sim.fish_dead[p] is not None]
        if sim.motor_dead:
            fire_t = next(e["t"] for e in sim.events if e["kind"] == "fire")
            message = f"The motor caught fire on {clock(fire_t)}. " + advice.get(
                "fire", "Check motor_temp(): when it's hot, switch off and let it cool down.")
        elif dead:
            if len(sc.ponds) == 1:
                message = f"The fish died on {clock(sim.fish_dead[1])}: pollution went above 8. "
            else:
                parts = [f"pond {p}'s on {clock(sim.fish_dead[p])}" for p in dead]
                message = "The fish died: " + " and ".join(parts) + ". "
            if result["code_done"] and result["code_end"] < sc.hours:
                message += (f"Your code finished on {clock(result['code_end'])}, so nothing was looking after "
                            "the pond after that. ")
            message += advice.get("fish", "")
        else:
            passed, message = level["goal"](sim, sc, ns, called)
        outcome = "win" if passed else "lose"
    result["outcome"] = outcome
    result["passed"] = passed
    result["message"] = message.strip()


def _pack(sim, sc, result):
    result["fish_dead"] = {p: sim.fish_dead[p] for p in sc.ponds}
    result["motor_hours"] = sim.motor_hours
    result["motor_dead"] = sim.motor_dead
    result["hours"] = sim.t
    return {"name": sc.name, "ponds": len(sc.ponds), "hours": sc.hours, "frames": sim.frames,
            "events": sim.events, "log": sim.log, "result": result}


def run_level(level_id, code):
    """Runs the student's code on every test case of a level. Returns JSON for the page."""
    level = LEVELS_BY_ID[int(level_id)]
    try:
        compiled = compile(code, USER_FILE, "exec")
    except SyntaxError as e:
        sc = level["cases"][0]
        sim = Sim(sc)
        msg = _syntax_message(e)
        sim.event("error", "Your code has a typo in it.")
        result = {"outcome": "error", "passed": False, "error": msg, "error_line": e.lineno,
                  "message": (f"Line {e.lineno}: " if e.lineno else "") + msg, "code_done": False, "code_end": 0}
        return json.dumps({"level": level["id"], "passed": False, "cases": [_pack(sim, sc, result)]})
    cases = [_run_case(level, sc, compiled) for sc in level["cases"]]
    return json.dumps({"level": level["id"], "passed": all(c["result"]["passed"] for c in cases), "cases": cases})


# ---------------- level goals: (sim, scenario, namespace, calls) -> (passed, message) ----------------
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _readings_by_time(sim, pond=1):
    seen = {}
    for t, p, v in sim.readings:
        if p == pond and t not in seen:
            seen[t] = v
    return seen


def _printed_numbers(sim):
    return [[float(x) for x in _NUMBER.findall(line)] for line in sim.printed]


def goal_change(sim, sc, ns, called):
    seen = _readings_by_time(sim)
    if not seen:
        return False, "Use pollution(1) to read the sensor in pond 1."
    if len(seen) < 2:
        return False, "You only read the sensor at one moment. Call wait() between your two readings so 3 hours pass."
    times = sorted(seen)
    first, last = seen[times[0]], seen[times[-1]]
    change = last - first
    if not any(abs(abs(x) - abs(change)) < 0.051 for nums in _printed_numbers(sim) for x in nums):
        return False, (f"Two readings: {first}, then {last}. Now work out how much it changed "
                       "(change = second - first) and print it.")
    state = "That's above 3, so the pond is no longer safe." if last > SAFE else "Still 3 or below, so safe for now."
    return True, f"Pollution went from {first} to {last} in {times[-1] - times[0]} hours, up {round(change, 1)}. {state}"


def goal_log(sim, sc, ns, called):
    seen = _readings_by_time(sim)
    n = len(seen)
    if n < 8:
        return False, (f"You took {n} reading{'' if n == 1 else 's'} at different times. "
                       "Take one every 3 hours for 24 hours: 8 in all.")
    values = [seen[t] for t in sorted(seen)]
    high, mean = max(values), sum(values) / len(values)
    # only count short lines, so printing the whole list doesn't count as printing the highest
    lines = [nums for nums in _printed_numbers(sim) if len(nums) <= 2]
    got_high = any(abs(x - high) < 0.051 for nums in lines for x in nums)
    got_mean = any(abs(x - mean) < 0.051 for nums in lines for x in nums)
    if not got_high and not got_mean:
        return False, (f"{n} readings logged. Now print the highest, max(readings), "
                       "and the average, sum(readings) / len(readings).")
    if not got_high:
        return False, "The average is there. Now print the highest reading on its own line too: max(readings)."
    if not got_mean:
        return False, "The highest is there. Now print the average: sum(readings) / len(readings)."
    extra = " The storm overflow pushed the pond well over the safe level of 3." if high > SAFE else ""
    return True, f"{n} readings: highest {high}, average {mean:.2f}.{extra}"


def goal_decide(sim, sc, ns, called):
    start = sc.start[1]
    if start > SAFE:
        if sim.ever_on:
            return True, f"Pollution was {start}, above 3, so the motor went on."
        return False, f"Pollution was {start}, which is above 3, but the motor never went on."
    if sim.ever_on:
        if start == SAFE:
            return False, (f"Pollution was exactly {start}. That isn't above 3, so the motor should stay off. "
                           "Did you use >= instead of >?")
        return False, f"Pollution was only {start}, so the pond is fine and the motor should stay off."
    return True, f"Pollution was {start}, not above 3, so the motor stayed off."


def _days(sc):
    return {1: "the whole day", 2: "both days"}.get(sc.hours // 24, f"all {sc.hours // 24} days")


def goal_survive(sim, sc, ns, called):
    peak = max(f[f"p{p}"] for f in sim.frames for p in sc.ponds)
    hottest = max(f["temp"] for f in sim.frames)
    return True, (f"Every fish survived {_days(sc)}. Highest pollution {peak:.1f}, hottest motor {hottest:.0f}°C, "
                  f"motor ran {sim.motor_hours} hours.")


def goal_function(sim, sc, ns, called):
    code = getattr(ns.get("clean"), "__code__", None)
    if code is None:
        return False, ("The fish survived, but this level is about writing your own function. Put your "
                       "pond-cleaning code inside def clean(pond): and call it for each pond.")
    if code.co_argcount != 1:
        return False, "clean should take one parameter, the pond number: def clean(pond):"
    if not called.get("clean"):
        return False, "You defined clean(pond) but never called it. Call clean(1) and clean(2)."
    return True, f"Both ponds survived {_days(sc)}, with clean() doing the work. The motor ran {sim.motor_hours} hours."


def goal_final(sim, sc, ns, called):
    return True, (f"Every fish survived all 4 days. The motor ran for {sim.motor_hours} hours. "
                  "Can you do it with fewer?")


# ---------------- the levels ----------------
LEVELS = [
    {
        "id": 1,
        "title": "Test the water",
        "axis": 3,
        "concepts": ["calling functions", "variables", "print()"],
        "uses": ["pollution", "wait", "print"],
        "story": (
            "You've just started as the environmental officer at a fish farm. Run-off from the farmyard drains "
            "into the pond, and a sensor in the water measures a **pollution index**: **3 or below** is "
            "healthy, but **above 8** the oxygen runs out and the fish suffocate.\n\n"
            "Before you change anything, find out what's going on."
        ),
        "task": "Read pond 1's sensor, wait 3 hours, read it again, and **print how much the pollution changed**.",
        "reminder": (
            'depth = 1.8                  # store a number in a variable\n'
            'print("Depth:", depth)       # print() shows it in the output box\n'
            'deeper = depth + 0.5         # use variables in sums\n'
        ),
        "starter": (
            "# pollution(1) reads the sensor in pond 1.\n"
            "# Save the reading in a variable so you can use it later.\n"
            "first = pollution(1)\n"
            'print("First reading:", first)\n'
            "\n"
            "# wait() lets 3 hours pass.\n"
            "wait()\n"
            "\n"
            "# Now take a second reading and print how much it changed.\n"
            "\n"
        ),
        "hint": "Copy the reading line, but call the new variable `second`. Then work out `change = second - first` and print it.",
        "answer": (
            "first = pollution(1)\n"
            'print("First reading:", first)\n'
            "\n"
            "wait()\n"
            "\n"
            "second = pollution(1)\n"
            'print("Second reading:", second)\n'
            "\n"
            "change = second - first\n"
            'print("Change in 3 hours:", round(change, 1))\n'
        ),
        "questions": [
            ("Was the pond safe at your first reading? And at the second?",
             "The first reading (2.4) is safe because it's 3 or below. Three hours later it's 3.1, just over "
             "the line, so it's no longer safe."),
            ("Without `round()`, Python prints the change as 0.7000000000000002. Why?",
             "Computers store decimals in binary, and most decimals (like 0.1 or 0.7) can't be stored exactly, "
             "so tiny errors creep into sums. `round(change, 1)` tidies it to 1 decimal place. Worth knowing "
             "before you ever compare decimals with `==`."),
            ("If it keeps rising like this, roughly how long until the fish are in danger (above 8)?",
             "A straight-line guess: it rose 0.7 in 3 hours and there's 4.9 to go, so about 21 hours. In this "
             "model it actually slows down, because a dirtier pond also cleans itself a little faster, so it "
             "would take closer to two days. Rates of change aren't always constant."),
        ],
        "cases": [Scenario("", hours=12, ponds=1, start={1: 2.4}, base=0.3, after_code=0)],
        "goal": goal_change,
    },
    {
        "id": 2,
        "title": "Sensor log",
        "axis": 24,
        "concepts": ["for loops", "range()", "lists", "max(), sum(), len()"],
        "uses": ["pollution", "wait", "print"],
        "story": (
            "One reading doesn't tell you much. Real monitoring means sampling at regular intervals and "
            "looking at the whole record.\n\n"
            "Heavy rain is forecast for this evening. When it pours, the village's **storm overflow** "
            "discharges sewage into the pond."
        ),
        "task": ("Take a reading every 3 hours for 24 hours (8 readings) and store them in a list. Then print "
                 "the **highest** reading and the **average**."),
        "reminder": (
            "rainfall = []                 # an empty list\n"
            "for day in range(3):          # repeats 3 times (day is 0, 1, 2)\n"
            "    rainfall.append(day * 4)  # add to the end of the list\n"
            "print(rainfall)               # [0, 4, 8]\n"
            "print(max(rainfall))          # 8\n"
            "print(sum(rainfall) / len(rainfall))   # 4.0\n"
        ),
        "starter": (
            "readings = []            # an empty list\n"
            "\n"
            "for i in range(8):       # the indented lines repeat 8 times\n"
            "    pass                 # replace this: read pond 1, add it to the list, wait\n"
            "\n"
            "print(readings)\n"
            "\n"
            "# Now print the highest reading and the average.\n"
        ),
        "hint": ("Inside the loop: `readings.append(pollution(1))` and then `wait()`. After the loop, "
                 "`max(readings)` is the highest and `sum(readings) / len(readings)` is the average."),
        "answer": (
            "readings = []\n"
            "\n"
            "for i in range(8):\n"
            "    readings.append(pollution(1))\n"
            "    wait()\n"
            "\n"
            "print(readings)\n"
            'print("Highest:", max(readings))\n'
            'print("Average:", round(sum(readings) / len(readings), 2))\n'
        ),
        "questions": [
            ("When was the highest reading taken, and what caused it?",
             "The 7th one (6.5), at 02:00 on day 2. The storm overflow started pouring sewage in at about "
             "20:00, and with no aerator running the pond can only clean itself very slowly, so it stays high."),
            ("You sampled every 3 hours. Could something important happen between samples?",
             "Yes. Your readings are the dots on the chart; the line is what really happened. The true peak "
             "(about 6.6, around 01:00) fell between two samples, so your highest reading is a bit lower. A "
             "short, sharp event could come and go between samples completely. Sampling more often costs "
             "more: battery, data, lab time."),
            ("Why isn't the average enough to tell you whether the fish are OK?",
             "Fish die from the worst moment, not the average. One short spike above 8 kills them even if the "
             "day's average looks healthy: the difference between acute and chronic exposure."),
        ],
        "cases": [Scenario("", hours=30, ponds=1, start={1: 1.8}, spills={1: [(13.5, 1.5, 5.4)]}, after_code=0)],
        "goal": goal_log,
    },
    {
        "id": 3,
        "title": "Switch it on",
        "axis": 3,
        "concepts": ["if / else", "comparisons"],
        "uses": ["pollution", "motor_on", "motor_off", "print"],
        "story": (
            "The farm has an **aerator**: a motor that pumps air down a hose to a bubbler on the pond bed. The "
            "extra oxygen helps microbes break down the pollution: each hour it runs, pollution drops by about "
            "1.5. But electricity costs money, so it should only run when the pond needs it."
        ),
        "task": ("Read pond 1. If the pollution is **above 3**, switch the motor on. Otherwise leave it off. "
                 "Your code is tested on three different mornings."),
        "reminder": (
            "river_temp = 24\n"
            "if river_temp > 20:\n"
            '    print("Too warm for trout")\n'
            "else:\n"
            '    print("Fine for trout")\n'
        ),
        "starter": (
            "level = pollution(1)\n"
            'print("Pollution is", level)\n'
            "\n"
            "# If level is above 3, switch the motor on with motor_on().\n"
            "# Otherwise, leave it off.\n"
        ),
        "hint": ("Start with `if level > 3:` and put `motor_on()` on the next line, indented by 4 spaces. "
                 "For the `else:` part you can call `motor_off()`."),
        "answer": (
            "level = pollution(1)\n"
            'print("Pollution is", level)\n'
            "\n"
            "if level > 3:\n"
            "    motor_on()\n"
            "else:\n"
            "    motor_off()\n"
        ),
        "questions": [
            ("One morning the reading is exactly 3.0. What's the difference between `>` and `>=` there?",
             "`3.0 > 3` is False, so the motor stays off. `3.0 >= 3` is True, so it would switch on. The "
             "borderline morning tests exactly this. Boundaries are where a lot of real bugs hide, so it's "
             "always worth testing them."),
            ("Your code makes one decision and stops. Why is that a problem if a storm arrives at lunchtime?",
             "Nothing checks the pond again. It could fill up with sewage while the motor's off, or the motor "
             "could run forever. You need to repeat the check, which is the next level."),
        ],
        "cases": [
            Scenario("Murky morning", hours=6, ponds=1, start={1: 5.2}, after_code=3),
            Scenario("Clear morning", hours=6, ponds=1, start={1: 1.9}, after_code=3),
            Scenario("Borderline morning", hours=6, ponds=1, start={1: 3.0}, after_code=3),
        ],
        "goal": goal_decide,
    },
    {
        "id": 4,
        "title": "Keep watch",
        "concepts": ["while loops", "repeating a check"],
        "uses": ["pollution", "motor_on", "motor_off", "wait"],
        "story": (
            "Storms are forecast for the next two days, and each one sets off the storm overflow. You can't "
            "stand by the pond for 48 hours, so let your code keep watch."
        ),
        "task": ("Every 3 hours, test the pond: if it's **above 3** switch the motor on, and if it's **3 or "
                 "below** switch it off. Keep the fish alive for 2 days."),
        "reminder": (
            "while True:              # repeats forever (here: until the 2 days are up)\n"
            '    print("Checking...")\n'
            "    wait()               # every loop needs wait(), or time stands still\n"
        ),
        "starter": (
            "while True:\n"
            "    level = pollution(1)\n"
            "\n"
            "    # motor on if level is above 3, off if it isn't\n"
            "\n"
            "    wait()\n"
        ),
        "hint": ("Put your if/else from level 3 inside the loop, before `wait()`. Make sure the motor goes "
                 "**off** when the pond is clean, or it will run until it overheats."),
        "answer": (
            "while True:\n"
            "    level = pollution(1)\n"
            "    if level > 3:\n"
            "        motor_on()\n"
            "    else:\n"
            "        motor_off()\n"
            "    wait()\n"
        ),
        "questions": [
            ("What happens if you leave out `wait()`? Try it.",
             "Time stops. The loop spins forever at the same moment, because only `wait()` (and later "
             "`switch_to()`) moves time on. The page spots this and stops your code."),
            ("Watch the motor temperature on the chart. What would happen if a storm lasted much longer?",
             "The motor heats up 15°C an hour and cools 8°C an hour. Two 3-hour runs back to back take it from "
             "20°C to 110°C, and it catches fire at 100°C. That's the next level."),
            ("This is called on/off (or 'bang-bang') control. Where else is it used?",
             "Home thermostats, fridges, immersion heaters, sump pumps, irrigation that switches on below a "
             "soil-moisture threshold. Simple and robust, but the thing it controls swings up and down."),
        ],
        "advice": {
            "fire": "It ran too long without a break. Switch it off once the pond is back to 3 or below.",
            "fish": "Check the pond every 3 hours and switch the motor on whenever it's above 3.",
        },
        "cases": [Scenario("", hours=48, ponds=1, start={1: 2.0},
                           spills={1: [(8, 1.2, 3.6), (24, 1.2, 3.6), (39, 1.2, 3.8)]})],
        "goal": goal_survive,
    },
    {
        "id": 5,
        "title": "Too hot",
        "concepts": ["nested loops", "while with a condition"],
        "uses": ["pollution", "motor_temp", "motor_on", "motor_off", "wait"],
        "carry": True,
        "story": (
            "A big storm: the overflow runs for hours, far more than one burst of aeration can deal with. "
            "While it runs the motor heats up **15°C an hour**; switched off it cools **8°C an hour**. "
            "At **100°C** it catches fire."
        ),
        "task": ("Keep the fish alive for 2 days **without setting the motor on fire**. When the motor gets "
                 "hot, switch it off and wait until it has cooled down."),
        "reminder": (
            "water_temp = 80\n"
            "while water_temp > 40:        # repeats while this is True\n"
            "    water_temp = water_temp - 15\n"
            "    print(water_temp)         # 65, 50, 35\n"
        ),
        "starter": (
            "# Your code from level 4. Run it and watch the motor temperature!\n"
            "# Then use motor_temp(): if the motor is too hot, switch it off\n"
            "# and keep waiting while it cools down.\n"
            "\n"
            "while True:\n"
            "    if pollution(1) > 3:\n"
            "        motor_on()\n"
            "    else:\n"
            "        motor_off()\n"
            "    wait()\n"
        ),
        "hint": ("Before switching on, check `motor_temp()`. If it's above about 50: `motor_off()`, then "
                 "`while motor_temp() > 20:` with `wait()` inside, so it cools right down. Otherwise switch "
                 "on and `wait()`."),
        "answer": (
            "while True:\n"
            "    if pollution(1) > 3:\n"
            "        if motor_temp() > 50:\n"
            "            motor_off()\n"
            "            while motor_temp() > 20:\n"
            "                wait()\n"
            "        else:\n"
            "            motor_on()\n"
            "            wait()\n"
            "    else:\n"
            "        motor_off()\n"
            "        wait()\n"
        ),
        "questions": [
            ("Try a limit of 70°C instead of 50°C. What goes wrong, and why?",
             "Your code only checks every 3 hours, and 3 hours of running adds 45°C. From 70°C that's 115°C: "
             "fire. To be safe you have to switch off at anything above 100 − 45 = 55°C. Thinking about the "
             "worst case between checks is a big part of control engineering."),
            ("The motor now spends most of its time cooling. What's the trade-off?",
             "Every hour it rests, pollution builds up again. Rest too long and the fish die; rest too little "
             "and the motor burns out. Finding that balance is what the final level is about."),
        ],
        "advice": {
            "fire": "Check motor_temp() before switching on. If it's hot, switch off and wait while it cools.",
            "fish": "The motor has to run as much as it safely can. Did it spend too long cooling?",
        },
        "cases": [Scenario("", hours=48, ponds=1, start={1: 1.5}, spills={1: [(14, 5, 14.0)]})],
        "goal": goal_survive,
    },
    {
        "id": 6,
        "title": "Two ponds",
        "concepts": ["def: your own functions", "parameters", "switch_to()"],
        "uses": ["pollution", "motor_temp", "motor_on", "motor_off", "switch_to", "wait"],
        "carry": True,
        "story": (
            "The farm's second pond needs looking after too, but there's only one motor. `switch_to()` moves "
            "the air hose to the other pond, which takes **3 hours**. Move it with the motor running and the "
            "hose whips round and soaks the farmer."
        ),
        "task": ("Write a function **`clean(pond)`** that moves the hose to that pond, runs the aerator (with "
                 "cool-downs) until the pond is safe, then switches the motor off. Use it to keep both ponds "
                 "alive for 2 days."),
        "reminder": (
            "def report(pond, level):            # a function with 2 parameters\n"
            '    print("Pond", pond, "is at", level)\n'
            "\n"
            "report(1, 2.5)     # Pond 1 is at 2.5\n"
            "report(2, 6.1)     # Pond 2 is at 6.1\n"
        ),
        "starter": (
            "def clean(pond):\n"
            "    switch_to(pond)\n"
            "    # While this pond's pollution is above 3, run the motor\n"
            "    # (with cool-downs, like level 5).\n"
            "    # When it's safe, switch the motor off.\n"
            "    pass\n"
            "\n"
            "while True:\n"
            "    clean(1)\n"
            "    clean(2)\n"
        ),
        "hint": ("Inside `clean`, use a `while pollution(pond) > 3:` loop containing your level 5 motor logic. "
                 "After the loop, call `motor_off()` so the hose is safe to move."),
        "answer": (
            "def clean(pond):\n"
            "    switch_to(pond)\n"
            "    while pollution(pond) > 3:\n"
            "        if motor_temp() > 50:\n"
            "            motor_off()\n"
            "            while motor_temp() > 20:\n"
            "                wait()\n"
            "        else:\n"
            "            motor_on()\n"
            "            wait()\n"
            "    motor_off()\n"
            "\n"
            "while True:\n"
            "    clean(1)\n"
            "    clean(2)\n"
        ),
        "questions": [
            ("Why write `clean()` as a function instead of copying the code out twice?",
             "There's one copy to read, test and fix. Change the temperature limit once and both ponds get it. "
             "And `clean(2)` says what it does, which makes the main loop easy to follow."),
            ("When both ponds are clean, what does your main loop actually do? Look at the output log.",
             "It moves the hose back and forth (each `switch_to()` takes 3 hours), checking each pond as it "
             "arrives. That's why time keeps moving even though the main loop has no `wait()`."),
            ("What happens to pond 2 while `clean(1)` is busy?",
             "Nothing checks it until `clean(1)` returns, so it can get much worse in the meantime. In the final "
             "level, that matters."),
        ],
        "advice": {
            "fire": "Check motor_temp() before switching on. If it's hot, switch off and wait while it cools.",
            "fish": "Did clean() stay with each pond until it was safe?",
        },
        "cases": [Scenario("", hours=48, ponds=2, start={1: 1.5, 2: 1.5},
                           spills={1: [(10, 5, 10.0)], 2: [(30, 5, 10.0)]})],
        "goal": goal_function,
    },
    {
        "id": 7,
        "title": "Pond Rescue",
        "concepts": ["putting it all together"],
        "uses": ["pollution", "motor_temp", "motor_on", "motor_off", "switch_to", "wait"],
        "carry": True,
        "bonus": True,
        "story": (
            "Four days, two ponds, three storm overflows. And on day 3 a barrel of chemicals falls into "
            "pond 1 and keeps leaking for hours."
        ),
        "task": ("Keep every fish alive for all 4 days without setting the motor on fire. **Bonus:** do it "
                 "with as few motor hours as you can."),
        "tips": [
            "A toxic spill keeps leaking after it lands. Leave too early and it creeps past 8 while you're away.",
            "When a pond dies, look at the chart: was the motor cooling down, or busy at the other pond?",
            "Your temperature limits matter. Try a few and watch the orange line.",
        ],
        "starter": (
            "# Everything comes together here. If you've done level 6,\n"
            "# the 'Start from my level 6 code' button above copies your\n"
            "# code in. Run it, see how it copes, then improve it.\n"
            "\n"
            "while True:\n"
            "    wait()\n"
        ),
        "hint": ("Your level 6 code is a good start. If a pond dies, look at the chart: was the motor cooling "
                 "down, or busy at the other pond? Try different temperature limits, and make sure you stay "
                 "with a pond until it's safe."),
        "answer": (
            "while True:\n"
            "    for pond in [1, 2]:\n"
            "        switch_to(pond)\n"
            "        while pollution(pond) > 3:\n"
            "            if motor_temp() > 50:\n"
            "                motor_off()\n"
            "                while motor_temp() > 20:\n"
            "                    wait()\n"
            "            else:\n"
            "                motor_on()\n"
            "                wait()\n"
            "        motor_off()\n"
        ),
        "questions": [
            ("With the toxic spill, which is the more dangerous mistake: leaving a pond too early, or staying too long?",
             "Leaving too early. The barrel keeps leaking after it lands, so if you move on as soon as pond 1 "
             "dips below 3, it creeps past 8 while you're at pond 2."),
            ("How few motor hours can you manage? What did you change?",
             "The answer above uses 30 hours. Adding a `wait()` at the end of each round brings it down to 27, "
             "because the ponds clean themselves a little while the motor rests. Every hour saved is less "
             "electricity and less wear on the motor."),
            ("This is a toy model. What would a real pond manager want that this code doesn't do?",
             "Alerts when something goes wrong, a plan for a broken or lying sensor, using the weather forecast "
             "to aerate before a storm arrives, records for the regulator, and backup equipment. Real control "
             "systems spend a lot of their code on what to do when things fail."),
        ],
        "advice": {
            "fire": "Check motor_temp() before switching on. If it's hot, switch off and wait while it cools.",
            "fish": "Look at the chart: when the fish died, was the motor cooling down, or busy at the other pond?",
        },
        "cases": [Scenario("", hours=HOURS, ponds=2, start=START_POLLUTION, spills=SPILLS, toxic=TOXIC)],
        "goal": goal_final,
    },
]
LEVELS_BY_ID = {lv["id"]: lv for lv in LEVELS}
FINAL_LEVEL = LEVELS[-1]["id"]


def level_for_page(lv):
    """The parts of a level the page needs before Python has loaded (build.py writes them into the page)."""
    first = lv["cases"][0]
    return {
        "id": lv["id"], "title": lv["title"], "concepts": lv["concepts"], "uses": lv["uses"],
        "story": lv["story"], "task": lv["task"], "reminder": lv.get("reminder"), "tips": lv.get("tips"),
        "starter": lv["starter"], "hint": lv["hint"], "answer": lv["answer"],
        "questions": [{"q": q, "a": a} for q, a in lv["questions"]],
        "carry": lv.get("carry", False), "bonus": lv.get("bonus", False),
        "tests": [sc.name for sc in lv["cases"]] if len(lv["cases"]) > 1 else [],
        "ponds": len(first.ponds), "hours": first.hours, "axis": lv.get("axis"), "preview": Sim(first).frames[0],
    }
