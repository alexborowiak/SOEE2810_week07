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

# ---------------- physics: the same in every question ----------------
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

# ---------------- the final challenge (question 14) ----------------
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
        self.switches = []     # (hour, 'on' or 'off') for every motor_on() / motor_off() call
        self.aer_hours = {p: 0 for p in sc.ponds}   # hours the motor spent cleaning each pond
        self.user_args = {}    # the student's own functions -> first arguments they were called with
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
            self.aer_hours[self.target] += 1
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
        sim.switches.append((sim.t, "on"))
        sim.ever_on = True
        if not sim.motor:
            sim.motor = True
            sim._update_snapshot()

    def motor_off():
        """Switch the motor off."""
        sim.tick_call()
        sim.log_call("motor_off")
        sim.switches.append((sim.t, "off"))
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
                code = frame.f_code
                if code.co_argcount:
                    first = frame.f_locals.get(code.co_varnames[0])
                    sim.user_args.setdefault(name, set()).add(repr(first))
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




# ---------------- question goals: (sim, scenario, namespace, calls) -> (passed, message) ----------------
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _readings_by_time(sim, pond=1):
    seen = {}
    for t, p, v in sim.readings:
        if p == pond and t not in seen:
            seen[t] = v
    return seen


def _printed_numbers(sim):
    return [[float(x) for x in _NUMBER.findall(line)] for line in sim.printed]


def _was_printed(sim, value):
    return any(abs(x - value) < 0.051 for nums in _printed_numbers(sim) for x in nums)


def _p_at(sim, t, pond=1):
    """True pollution at hour t (what a reading then would have shown)."""
    return round(sim.frames[min(max(t, 0), len(sim.frames) - 1)][f"p{pond}"], 1)


def _days(sc):
    return {1: "the whole day", 2: "both days"}.get(sc.hours // 24, f"all {sc.hours // 24} days")


def goal_print_reading(sim, sc, ns, called):
    seen = _readings_by_time(sim)
    if not seen:
        return False, "Call pollution(1) to read the sensor."
    value = seen[min(seen)]
    if not _was_printed(sim, value):
        return False, "You read the sensor but didn't print the reading. Put it inside print( )."
    return True, f"Pond 1 is at {value}. That's safe: 3 or below."


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
                       "(second - first) and print it.")
    state = "That's above 3, so the pond is no longer safe." if last > SAFE else "Still 3 or below, so safe for now."
    return True, f"Pollution went from {first} to {last} in {times[-1] - times[0]} hours, up {round(change, 1)}. {state}"


def goal_four(sim, sc, ns, called):
    seen = _readings_by_time(sim)
    if len(seen) < 4:
        return False, (f"You read the sensor at {len(seen)} different time{'' if len(seen) == 1 else 's'}. "
                       "Read it 4 times, with a wait() each time round the loop.")
    printed = [t for t in sorted(seen) if _was_printed(sim, seen[t])]
    if len(printed) < 4:
        return False, f"You took {len(seen)} readings but printed {len(printed)} of them. Print each one."
    values = ", ".join(str(seen[t]) for t in sorted(seen)[:4])
    return True, f"Readings: {values}. It's creeping up every 3 hours."


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
    return True, f"{n} readings: highest {high}, average {mean:.2f}. The storm pushed the pond well over 3."


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


def goal_label(sim, sc, ns, called):
    start = sc.start[1]
    want = "danger" if start > 6 else "warning" if start > SAFE else "ok"
    words = {w for line in sim.printed for w in re.findall(r"[a-z]+", line.lower())} & {"danger", "warning", "ok"}
    if not words:
        return False, f"Pollution was {start}. Print danger, warning or ok."
    if words != {want}:
        said = " and ".join(sorted(words))
        return False, (f"Pollution was {start}, so it should say {want}, but your code printed {said}. "
                       "Python checks if and elif in order and stops at the first one that's True.")
    return True, f"Pollution was {start}: {want}."


def goal_dirtier(sim, sc, ns, called):
    dirty = max(sc.ponds, key=lambda p: sc.start[p])
    clean = min(sc.ponds, key=lambda p: sc.start[p])
    if sim.aer_hours[dirty] == 0:
        if sim.aer_hours[clean]:
            return False, f"Pond {dirty} was the dirtier one ({sc.start[dirty]}), but the motor cleaned pond {clean}."
        return False, f"Pond {dirty} was dirtier ({sc.start[dirty]}). Move the hose there and switch the motor on."
    if sim.aer_hours[clean]:
        return False, f"The motor also ran on pond {clean}, which was already clean ({sc.start[clean]})."
    return True, f"Pond {dirty} was dirtier ({sc.start[dirty]} against {sc.start[clean]}), and that's the one you cleaned."


def goal_wait_storm(sim, sc, ns, called):
    ons = [t for t, what in sim.switches if what == "on"]
    if not ons:
        return False, "The motor never went on. Wait until the pond is above 3, then call motor_on()."
    t = ons[0]
    if _p_at(sim, t) <= SAFE:
        return False, f"You switched on at {clock(t)}, when the pond was only {_p_at(sim, t)}. Wait until it's above 3."
    if t >= 3 and _p_at(sim, t - 3) > SAFE:
        return False, (f"The pond was already above 3 at {clock(t - 3)}, but the motor only went on at {clock(t)}. "
                       "Check every 3 hours.")
    return True, f"The pond went above 3 and the motor went on straight away, at {clock(t)}."


def goal_stop_clean(sim, sc, ns, called):
    on = [t for t, what in sim.switches if what == "on"]
    if not on:
        return False, "Keep the motor_on() at the top: the motor has to be running to start with."
    offs = [t for t, what in sim.switches if what == "off" and t >= on[0]]
    if not offs:
        return False, "The motor never went off. Once the pond is 3 or below, call motor_off()."
    t = offs[0]
    if _p_at(sim, t) > SAFE:
        return False, (f"You switched off at {clock(t)}, when the pond was still {_p_at(sim, t)}. "
                       "Keep going while it's above 3.")
    if t >= 3 and _p_at(sim, t - 3) <= SAFE:
        return False, (f"The pond was already clean at {clock(t - 3)}, but the motor ran on until {clock(t)}. "
                       "Check the pond before waiting, not after.")
    if t == 0:
        return True, f"The pond was already clean ({sc.start[1]}), so the motor went straight off."
    return True, f"The motor ran until the pond was clean, then went off at {clock(t)}."


def goal_survive(sim, sc, ns, called):
    peak = max(f[f"p{p}"] for f in sim.frames for p in sc.ponds)
    hottest = max(f["temp"] for f in sim.frames)
    return True, (f"Every fish survived {_days(sc)}. Highest pollution {peak:.1f}, hottest motor {hottest:.0f}°C, "
                  f"motor ran {sim.motor_hours} hours.")


def goal_report(sim, sc, ns, called):
    code = getattr(ns.get("report"), "__code__", None)
    if code is None:
        return False, "Define the function first: def report(pond):"
    if code.co_argcount != 1:
        return False, "report should take one parameter, the pond number: def report(pond):"
    args = sim.user_args.get("report", set())
    if any(repr(p) not in args for p in sc.ponds):
        return False, "Call report() for both ponds: report(1) and report(2)."
    for p in sc.ponds:
        if not any(rp == p and _was_printed(sim, v) for _, rp, v in sim.readings):
            return False, f"report({p}) should print pond {p}'s pollution. Use pollution(pond) inside the function."
    return True, "One function, used twice. Pond 1 needs the motor; pond 2 is fine."


def goal_function(sim, sc, ns, called):
    code = getattr(ns.get("clean"), "__code__", None)
    if code is None:
        return False, ("The fish survived, but this question is about writing your own function. Put your "
                       "pond-cleaning code inside def clean(pond): and call it for each pond.")
    if code.co_argcount != 1:
        return False, "clean should take one parameter, the pond number: def clean(pond):"
    if not called.get("clean"):
        return False, "You defined clean(pond) but never called it. Call clean(1) and clean(2)."
    return True, f"Both ponds survived {_days(sc)}, with clean() doing the work. The motor ran {sim.motor_hours} hours."


def goal_final(sim, sc, ns, called):
    return True, (f"Every fish survived all 4 days. The motor ran for {sim.motor_hours} hours. "
                  "Can you do it with fewer?")


# ---------------- the questions ----------------
# Text can use `code` and **bold**. Each answer is what the page reveals and what check_scenario.py tests.
COOL = {"fire": "Check motor_temp() before switching on. If it's hot, switch off and wait while it cools."}

LEVELS = [
    {
        "id": 1, "title": "Read the sensor", "topic": "calling a function",
        "uses": ["pollution", "print"], "axis": 3,
        "task": "`pollution(1)` reads the sensor in pond 1. **Print** what it says.",
        "starter": "# Print the reading from pond 1's sensor.\n",
        "hint": "Put the function call inside `print( )`, like this: `print(pollution(1))`.",
        "answer": "print(pollution(1))\n",
        "cases": [Scenario("", hours=12, ponds=1, start={1: 2.4}, base=0.3, after_code=0)],
        "goal": goal_print_reading,
    },
    {
        "id": 2, "title": "Is it getting worse?", "topic": "variables",
        "uses": ["pollution", "wait", "print"], "axis": 3,
        "task": "Read pond 1, `wait()` 3 hours, read it again, and **print how much it changed**.",
        "starter": (
            "first = pollution(1)\n"
            "wait()\n"
            "\n"
            "# read it again, then print how much it changed\n"
        ),
        "hint": "Save the second reading in a variable too: `second = pollution(1)`. Then print `second - first`.",
        "answer": (
            "first = pollution(1)\n"
            "wait()\n"
            "second = pollution(1)\n"
            "print(round(second - first, 1))\n"
        ),
        "cases": [Scenario("", hours=12, ponds=1, start={1: 2.4}, base=0.3, after_code=0)],
        "goal": goal_change,
    },
    {
        "id": 3, "title": "Four readings", "topic": "for loops",
        "uses": ["pollution", "wait", "print"], "axis": 12,
        "task": "Use a `for` loop to read pond 1 **four times**, 3 hours apart, printing each reading.",
        "starter": (
            "for i in range(4):\n"
            "    # print a reading, then wait\n"
            "    pass\n"
        ),
        "hint": "Replace `pass` with two indented lines: `print(pollution(1))` and `wait()`.",
        "answer": (
            "for i in range(4):\n"
            "    print(pollution(1))\n"
            "    wait()\n"
        ),
        "cases": [Scenario("", hours=15, ponds=1, start={1: 2.0}, base=0.3, after_code=0)],
        "goal": goal_four,
    },
    {
        "id": 4, "title": "Highest and average", "topic": "lists",
        "uses": ["pollution", "wait", "print"], "axis": 24,
        "task": ("A storm is due tonight. This code keeps 8 readings, 3 hours apart, in a list. Add lines to print "
                 "the **highest** reading and the **average**."),
        "starter": (
            "readings = []\n"
            "\n"
            "for i in range(8):\n"
            "    readings.append(pollution(1))\n"
            "    wait()\n"
            "\n"
            "# print the highest and the average\n"
        ),
        "hint": "`max(readings)` gives the highest. The average is `sum(readings) / len(readings)`.",
        "answer": (
            "readings = []\n"
            "\n"
            "for i in range(8):\n"
            "    readings.append(pollution(1))\n"
            "    wait()\n"
            "\n"
            "print(max(readings))\n"
            "print(sum(readings) / len(readings))\n"
        ),
        "cases": [Scenario("", hours=30, ponds=1, start={1: 1.8}, spills={1: [(13.5, 1.5, 5.4)]}, after_code=0)],
        "goal": goal_log,
    },
    {
        "id": 5, "title": "Switch it on", "topic": "if",
        "uses": ["pollution", "motor_on", "motor_off"], "axis": 3,
        "task": ("The aerator pumps air into the pond and cleans it. If pond 1 is **above 3**, switch it on with "
                 "`motor_on()`. Otherwise leave it off. Your code is tested on three mornings."),
        "starter": (
            "level = pollution(1)\n"
            "\n"
            "# if level is above 3, switch the motor on\n"
        ),
        "hint": "`if level > 3:` then `motor_on()` on the next line, indented by 4 spaces.",
        "answer": (
            "level = pollution(1)\n"
            "\n"
            "if level > 3:\n"
            "    motor_on()\n"
        ),
        "cases": [
            Scenario("Murky", hours=6, ponds=1, start={1: 5.2}, after_code=3),
            Scenario("Clear", hours=6, ponds=1, start={1: 1.9}, after_code=3),
            Scenario("Exactly 3", hours=6, ponds=1, start={1: 3.0}, after_code=3),
        ],
        "goal": goal_decide,
    },
    {
        "id": 6, "title": "Danger, warning or ok", "topic": "elif",
        "uses": ["pollution", "print"], "axis": 3,
        "task": "Read pond 1 and print **danger** if it's above 6, **warning** if it's above 3, otherwise **ok**.",
        "starter": (
            "level = pollution(1)\n"
            "\n"
            "if level > 6:\n"
            '    print("danger")\n'
        ),
        "hint": "Add `elif level > 3:` for the warning, then `else:` for ok. Python stops at the first match.",
        "answer": (
            "level = pollution(1)\n"
            "\n"
            "if level > 6:\n"
            '    print("danger")\n'
            "elif level > 3:\n"
            '    print("warning")\n'
            "else:\n"
            '    print("ok")\n'
        ),
        "cases": [
            Scenario("7.0", hours=3, ponds=1, start={1: 7.0}, after_code=0),
            Scenario("4.5", hours=3, ponds=1, start={1: 4.5}, after_code=0),
            Scenario("2.0", hours=3, ponds=1, start={1: 2.0}, after_code=0),
        ],
        "goal": goal_label,
    },
    {
        "id": 7, "title": "Which pond?", "topic": "comparing values",
        "uses": ["pollution", "switch_to", "motor_on"], "axis": 9,
        "task": ("Two ponds, one hose. Read both, move the hose to the **dirtier** one with `switch_to()`, "
                 "then switch the motor on."),
        "starter": (
            "one = pollution(1)\n"
            "two = pollution(2)\n"
            "\n"
            "# move the hose to the dirtier pond, then switch the motor on\n"
        ),
        "hint": "`if one > two:` then `switch_to(1)`, `else:` then `switch_to(2)`. Finally `motor_on()`.",
        "answer": (
            "one = pollution(1)\n"
            "two = pollution(2)\n"
            "\n"
            "if one > two:\n"
            "    switch_to(1)\n"
            "else:\n"
            "    switch_to(2)\n"
            "motor_on()\n"
        ),
        "cases": [
            Scenario("Pond 1 dirtier", hours=9, ponds=2, start={1: 5.5, 2: 2.0}, after_code=3),
            Scenario("Pond 2 dirtier", hours=9, ponds=2, start={1: 2.0, 2: 5.5}, after_code=3),
        ],
        "goal": goal_dirtier,
    },
    {
        "id": 8, "title": "Wait for the storm", "topic": "while loops",
        "uses": ["pollution", "wait", "motor_on"], "axis": 24,
        "task": "A storm is coming. Keep waiting while pond 1 is **3 or below**, then switch the motor on.",
        "starter": (
            "# keep waiting while the pond is 3 or below\n"
            "\n"
            "motor_on()\n"
        ),
        "hint": "`while pollution(1) <= 3:` with `wait()` indented inside it. The loop ends once it's above 3.",
        "answer": (
            "while pollution(1) <= 3:\n"
            "    wait()\n"
            "\n"
            "motor_on()\n"
        ),
        "cases": [
            Scenario("Evening storm", hours=30, ponds=1, start={1: 1.8}, spills={1: [(13.5, 1.5, 5.4)]}, after_code=3),
            Scenario("Morning storm", hours=30, ponds=1, start={1: 1.8}, spills={1: [(5.5, 1.5, 5.4)]}, after_code=3),
        ],
        "goal": goal_wait_storm,
    },
    {
        "id": 9, "title": "Stop when it's clean", "topic": "while loops",
        "uses": ["pollution", "wait", "motor_on", "motor_off"], "axis": 6,
        "task": "The motor is on. Keep it running while pond 1 is **above 3**, then switch it off.",
        "starter": (
            "motor_on()\n"
            "\n"
            "# keep waiting while the pond is above 3, then switch the motor off\n"
        ),
        "hint": "`while pollution(1) > 3:` with `wait()` inside, then `motor_off()` after the loop (not indented).",
        "answer": (
            "motor_on()\n"
            "\n"
            "while pollution(1) > 3:\n"
            "    wait()\n"
            "\n"
            "motor_off()\n"
        ),
        "cases": [
            Scenario("Dirty pond", hours=12, ponds=1, start={1: 6.0}, after_code=3),
            Scenario("Already clean", hours=12, ponds=1, start={1: 2.6}, after_code=3),
        ],
        "goal": goal_stop_clean,
    },
    {
        "id": 10, "title": "Keep watch", "topic": "while True",
        "uses": ["pollution", "motor_on", "motor_off", "wait"],
        "task": ("Two days of storms. Over and over: check pond 1, motor **on** if it's above 3, **off** if not, "
                 "then `wait()`. Keep the fish alive."),
        "starter": (
            "while True:\n"
            "    level = pollution(1)\n"
            "\n"
            "    # motor on if level is above 3, off if not\n"
            "\n"
            "    wait()\n"
        ),
        "hint": "Inside the loop, before `wait()`: `if level > 3:` then `motor_on()`, `else:` then `motor_off()`.",
        "answer": (
            "while True:\n"
            "    level = pollution(1)\n"
            "    if level > 3:\n"
            "        motor_on()\n"
            "    else:\n"
            "        motor_off()\n"
            "    wait()\n"
        ),
        "advice": {
            "fire": "It ran too long without a break. Switch it off once the pond is back to 3 or below.",
            "fish": "Check the pond every 3 hours and switch the motor on whenever it's above 3.",
        },
        "cases": [Scenario("", hours=48, ponds=1, start={1: 2.0},
                           spills={1: [(8, 1.2, 3.6), (24, 1.2, 3.6), (39, 1.2, 3.8)]})],
        "goal": goal_survive,
    },
    {
        "id": 11, "title": "Too hot", "topic": "nested loops",
        "uses": ["pollution", "motor_temp", "motor_on", "motor_off", "wait"], "carry": True,
        "task": ("A long storm. Run this and watch the motor: it heats up 15°C an hour and catches fire at 100°C. "
                 "Fix it: when `motor_temp()` is high, switch off and wait for it to cool down."),
        "starter": (
            "while True:\n"
            "    if pollution(1) > 3:\n"
            "        motor_on()\n"
            "    else:\n"
            "        motor_off()\n"
            "    wait()\n"
        ),
        "hint": ("Before `motor_on()`, check `if motor_temp() > 50:`. If so: `motor_off()`, then "
                 "`while motor_temp() > 20:` with `wait()` inside."),
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
        "advice": dict(COOL, fish="The motor has to run as much as it safely can. Did it spend too long cooling?"),
        "cases": [Scenario("", hours=48, ponds=1, start={1: 1.5}, spills={1: [(14, 5, 14.0)]})],
        "goal": goal_survive,
    },
    {
        "id": 12, "title": "Your own function", "topic": "def",
        "uses": ["pollution", "print"], "axis": 3,
        "task": "Finish the function `report(pond)` so it prints that pond's pollution. It's used for both ponds.",
        "starter": (
            "def report(pond):\n"
            "    # print this pond's pollution\n"
            "    pass\n"
            "\n"
            "report(1)\n"
            "report(2)\n"
        ),
        "hint": 'Use the parameter inside the function: `print("Pond", pond, pollution(pond))`.',
        "answer": (
            "def report(pond):\n"
            '    print("Pond", pond, pollution(pond))\n'
            "\n"
            "report(1)\n"
            "report(2)\n"
        ),
        "cases": [Scenario("", hours=6, ponds=2, start={1: 4.2, 2: 1.9}, after_code=0)],
        "goal": goal_report,
    },
    {
        "id": 13, "title": "Two ponds", "topic": "functions and loops",
        "uses": ["pollution", "motor_temp", "motor_on", "motor_off", "switch_to", "wait"],
        "task": ("Finish `clean(pond)`: run the motor (with cool-downs) until that pond is safe, then switch off. "
                 "The loop at the bottom uses it to look after both ponds for 2 days."),
        "starter": (
            "def clean(pond):\n"
            "    switch_to(pond)\n"
            "    # while this pond is above 3, run the motor (cool it down when it's hot)\n"
            "    # then switch the motor off\n"
            "    pass\n"
            "\n"
            "while True:\n"
            "    clean(1)\n"
            "    clean(2)\n"
        ),
        "hint": ("Use `while pollution(pond) > 3:` with your motor code from question 11 inside it. After the loop, "
                 "`motor_off()`: the hose can only move when the motor is off."),
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
        "advice": dict(COOL, fish="Did clean() stay with each pond until it was safe?"),
        "cases": [Scenario("", hours=48, ponds=2, start={1: 1.5, 2: 1.5},
                           spills={1: [(10, 5, 10.0)], 2: [(30, 5, 10.0)]})],
        "goal": goal_function,
    },
    {
        "id": 14, "title": "Pond Rescue", "topic": "the full challenge",
        "uses": ["pollution", "motor_temp", "motor_on", "motor_off", "switch_to", "wait"], "carry": True,
        "bonus": True,
        "task": ("Four days, two ponds, three storms, and on day 3 a barrel of chemicals falls into pond 1 and keeps "
                 "leaking. Keep every fish alive without setting the motor on fire. **Bonus:** use the motor for as "
                 "few hours as you can."),
        "starter": (
            "# Tip: the button above copies in your question 13 code.\n"
            "\n"
            "while True:\n"
            "    wait()\n"
        ),
        "hint": ("Your question 13 code is a good start. If a pond dies, look at the chart: was the motor cooling "
                 "down, or busy at the other pond? The toxic leak keeps going, so don't leave pond 1 too early."),
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
        "advice": dict(COOL, fish="Look at the chart: when the fish died, was the motor cooling down, or busy at the other pond?"),
        "cases": [Scenario("", hours=HOURS, ponds=2, start=START_POLLUTION, spills=SPILLS, toxic=TOXIC)],
        "goal": goal_final,
    },
]
LEVELS_BY_ID = {lv["id"]: lv for lv in LEVELS}
FINAL_LEVEL = LEVELS[-1]["id"]


def level_for_page(lv):
    """The parts of a question the page needs before Python has loaded (build.py writes them into the page)."""
    first = lv["cases"][0]
    return {
        "id": lv["id"], "title": lv["title"], "topic": lv["topic"], "uses": lv["uses"], "task": lv["task"],
        "starter": lv["starter"], "hint": lv["hint"], "answer": lv["answer"],
        "carry": lv.get("carry", False), "bonus": lv.get("bonus", False),
        "tests": [sc.name for sc in lv["cases"]] if len(lv["cases"]) > 1 else [],
        "ponds": len(first.ponds), "hours": first.hours, "axis": lv.get("axis"), "preview": Sim(first).frames[0],
    }
