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
SENSOR_HOURS = 3      # wait() with no number waits this long
DECAY = 0.03          # natural clean-up per hour (fraction)
BASE_INFLOW = 0.045   # background pollution per hour
START_CLOCK = 8       # every run starts at 08:00 on day 1

# ---------------- the final challenge (question 24) ----------------
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
LOG_LIMIT = 6000      # lines, calls and prints kept for the page
TICK_LOG_LIMIT = 150   # ... and at most this many in any one hour


def clock(t):
    h = START_CLOCK + int(t)
    return f"Day {h // 24 + 1}, {h % 24:02d}:00"


class Scenario:
    """One test case: how long it runs, how many ponds, and what pours into them."""

    def __init__(self, name="", hours=HOURS, ponds=2, start=None, spills=None, toxic=(),
                 base=BASE_INFLOW, after_code=None, temp=START_TEMP, motor=False):
        self.name = name
        self.hours = hours
        self.ponds = tuple(range(1, ponds + 1))
        self.start = dict(start) if start else {p: 1.5 for p in self.ponds}
        self.spills = {p: list((spills or {}).get(p, [])) for p in self.ponds}
        self.toxic = list(toxic)
        self.base = dict(base) if isinstance(base, dict) else {p: base for p in self.ponds}
        # hours the ponds carry on once the student's code has finished (None: to the end)
        self.after_code = after_code
        self.temp = temp   # the motor's temperature at the start
        self.motor = motor   # whether the motor is already running

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


def _user_frame():
    """The frame of the student's code that is running right now."""
    f = sys._getframe(1)
    while f is not None and f.f_code.co_filename != USER_FILE:
        f = f.f_back
    return f


def _user_line():
    """Line number in the student's code that is running right now."""
    f = _user_frame()
    return f.f_lineno if f is not None else None


_SHOWN_TYPES = (int, float, str, bool, list, tuple, dict, type(None))


def _var_view(frame, hidden):
    """The student's variables as text, for the page's variables panel."""
    def show(ns):
        out = {}
        for name, value in ns.items():
            if name.startswith("__") or name in hidden or not isinstance(value, _SHOWN_TYPES):
                continue
            text = repr(value)
            out[name] = text if len(text) <= 70 else text[:67] + "..."
        return out
    view = {"g": show(frame.f_globals)}
    if frame.f_code.co_name != "<module>":
        view["f"] = frame.f_code.co_name
        view["l"] = show(frame.f_locals)
    return view


class Sim:
    def __init__(self, sc):
        self.sc = sc
        self.t = 0
        self.P = {p: float(sc.start[p]) for p in sc.ponds}
        self.temp = sc.temp
        self.motor = sc.motor
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
        self.hidden = set()    # names the page shouldn't list as variables (the pond functions)
        self.last_vars = None
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
        frame = _user_frame()
        entry = {"k": "call", "t": self.t, "line": frame.f_lineno if frame else None, "fn": fn, "args": args}
        self._add_vars(entry, frame)
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
            entry = {"k": "print", "t": self.t, "line": line, "text": text}
            self._add_vars(entry, _user_frame())
            self.log.append(entry)

    def log_line(self, frame):
        """A line of the student's code is about to run."""
        if len(self.log) >= LOG_LIMIT or self.logged_this_tick >= TICK_LOG_LIMIT:
            return
        self.logged_this_tick += 1
        entry = {"k": "line", "t": self.t, "line": frame.f_lineno}
        self._add_vars(entry, frame)
        self.log.append(entry)

    def _add_vars(self, entry, frame):
        # only when they've changed since the last entry; the page carries them forward
        if frame is None:
            return
        view = _var_view(frame, self.hidden)
        if view != self.last_vars:
            entry["vars"] = view
            self.last_vars = view

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
        """Let time pass: wait() is 3 hours, wait(x) is x hours. Zero or less lets no time pass."""
        shown = "" if hours is None else repr(hours)
        if hours is None:
            hours = SENSOR_HOURS
        if isinstance(hours, bool) or not isinstance(hours, (int, float)):
            raise PondError(f"wait({hours!r}): give it a number of hours, e.g. wait(3).")
        hours = max(0, int(hours))   # the ponds move on in whole hours
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
    sim.hidden = set(ns)
    called = {}   # the student's own functions -> how many times they were called

    def local_tracer(frame, event, arg):
        if event == "line":
            if sim.halt is not None:
                raise sim.halt()
            sim.lines_since_tick += 1
            if sim.lines_since_tick > LINE_LIMIT:
                sim.halt = _TimeFrozen
                raise _TimeFrozen()
            sim.log_line(frame)
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
        result["error"] = ("Time stopped! Your code is going round a loop without ever calling wait(3), "
                           "so no time passes. Add a wait(3) inside the loop.")
        sim.event("frozen", "Time stopped! No wait(3) in your loop.")
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
    # say when things happened only in questions where time passes (they use wait() or move the hose)
    timed = bool({"wait", "switch_to"} & set(level["uses"]))
    on = (lambda t: f" on {clock(t)}") if timed else (lambda t: "")
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
            message = f"The motor caught fire{on(fire_t)}. " + advice.get(
                "fire", "Check motor_temp(): when it's hot, switch off and let it cool down.")
        elif dead:
            if len(sc.ponds) == 1:
                message = f"The fish died{on(sim.fish_dead[1])}: pollution went above 8. "
            else:
                parts = [f"pond {p}'s{on(sim.fish_dead[p])}" for p in dead]
                message = "The fish died: " + " and ".join(parts) + ". "
            if timed and result["code_done"] and result["code_end"] < sc.hours:
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


def goal_headroom(sim, sc, ns, called):
    seen = _readings_by_time(sim)
    if not seen:
        return False, "Read pond 1's sensor with pollution(1)."
    value = seen[min(seen)]
    want = round(SAFE - value, 1)
    if _was_printed(sim, want):
        return True, f"Pond 1 is at {value}, so it's {want} below the safe limit of 3."
    if _was_printed(sim, -want):
        return False, f"You printed {-want}: that's the other way round. Take the reading away from 3."
    if _was_printed(sim, value):
        return False, f"You printed the reading ({value}). How far below 3 is that? Work it out with a subtraction."
    if not sim.printed:
        return False, "Nothing was printed. Put your sum inside print( )."
    return False, f"Pond 1 was at {value}, so the answer is 3 minus that."


def goal_change(sim, sc, ns, called):
    seen = _readings_by_time(sim)
    if not seen:
        return False, "Use pollution(1) to read the sensor in pond 1."
    if len(seen) < 2:
        return False, "You only read the sensor at one moment. Call wait(3) between your two readings so 3 hours pass."
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
                       "Read it 4 times, with a wait(3) each time round the loop.")
    printed = [t for t in sorted(seen) if _was_printed(sim, seen[t])]
    if len(printed) < 4:
        return False, f"You took {len(seen)} readings but printed {len(printed)} of them. Print each one."
    values = ", ".join(str(seen[t]) for t in sorted(seen)[:4])
    return True, f"Readings: {values}. It's creeping up every 3 hours."


def goal_list(sim, sc, ns, called):
    seen = _readings_by_time(sim)
    values = [seen[t] for t in sorted(seen)]
    if len(values) < 4:
        return False, (f"You read the sensor at {len(values)} different time{'' if len(values) == 1 else 's'}. "
                       "Take 4 readings, with a wait in between.")
    lines = _printed_numbers(sim)
    if any(len(nums) >= 4 and all(any(abs(x - v) < 0.051 for x in nums) for v in values[:4]) for nums in lines):
        return True, f"All four readings in one list: {values[:4]}."
    if sum(1 for nums in lines if len(nums) == 1) >= 4:
        return False, "You printed each reading on its own line. Keep them in a list instead, and print the list once at the end."
    return False, "Keep the readings in a list with readings.append(...), and print the list at the end."


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


def goal_switch_off(sim, sc, ns, called):
    start = sc.start[1]
    went_off = any(what == "off" for _, what in sim.switches)
    if start <= SAFE:
        if went_off:
            return True, f"Pollution was {start}, 3 or below, so the motor went off. That saves money."
        if start == SAFE:
            return False, (f"Pollution was exactly {start}. That's safe (3 or below), so the motor should go off. "
                           "Did you use < instead of <=?")
        return False, f"Pollution was {start}, so the pond is clean and the motor should go off."
    if went_off:
        return False, f"Pollution was {start}, which is above 3, so the motor should keep running."
    return True, f"Pollution was {start}, above 3, so the motor kept running."


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


def _said(sim, phrases):
    text = " ".join(sim.printed).lower()
    return {p for p in phrases if p in text}


def goal_both_clean(sim, sc, ns, called):
    a, b = sc.start[1], sc.start[2]
    want = "all clear" if a <= SAFE and b <= SAFE else "check ponds"
    why = (f"Pond 1 is {a}, so pond 1 <= 3 is {a <= SAFE}. Pond 2 is {b}, so pond 2 <= 3 is {b <= SAFE}. "
           f"{a <= SAFE} and {b <= SAFE} gives {a <= SAFE and b <= SAFE}")
    said = _said(sim, ["all clear", "check ponds"])
    if not said:
        return False, f"Print all clear or check ponds. ({why}.)"
    if said != {want}:
        return False, (f"{why}, so it should say {want}, but your code printed {' and '.join(sorted(said))}. "
                       "Each side of and needs its own comparison.")
    return True, f"{why}: {want}."


def goal_alarm(sim, sc, ns, called):
    a, b = sc.start[1], sc.start[2]
    want = "alarm" if a > 6 or b > 6 else "fine"
    why = (f"Pond 1 is {a}, so pond 1 > 6 is {a > 6}. Pond 2 is {b}, so pond 2 > 6 is {b > 6}. "
           f"{a > 6} or {b > 6} gives {a > 6 or b > 6}")
    said = _said(sim, ["alarm", "fine"])
    if not said:
        return False, f"Print alarm or fine. ({why}.)"
    if said != {want}:
        return False, (f"{why}, so it should say {want}, but your code printed {' and '.join(sorted(said))}. "
                       "or is True when either side is True; and needs both.")
    return True, f"{why}: {want}."


def _truth_goal(explain):
    """A question whose code prints a True/False condition. explain(sc) gives (the right answer, why)."""
    def goal(sim, sc, ns, called):
        want, why = explain(sc)
        said = {w for line in sim.printed for w in re.findall(r"\b(True|False)\b", line)}
        if not said:
            return False, f"Print the condition itself, inside print( ), and Python prints True or False. ({why}.)"
        if said != {str(want)}:
            return False, f"{why}, but your code printed {' and '.join(sorted(said))}."
        return True, f"{why}."
    return goal


def _tf_one(sc):
    p = sc.start[1]
    return p > SAFE, f"Pond 1 was {p}, so pollution(1) > 3 is {p > SAFE}"


def _tf_both(sc):
    a, b = sc.start[1] <= SAFE, sc.start[2] <= SAFE
    return a and b, (f"Pond 1 was {sc.start[1]}, so pollution(1) <= 3 is {a}. Pond 2 was {sc.start[2]}, so "
                     f"pollution(2) <= 3 is {b}. {a} and {b} is {a and b}")


def _tf_either(sc):
    a, b = sc.start[1] > 6, sc.start[2] > 6
    return a or b, (f"Pond 1 was {sc.start[1]}, so pollution(1) > 6 is {a}. Pond 2 was {sc.start[2]}, so "
                    f"pollution(2) > 6 is {b}. {a} or {b} is {a or b}")


def _tf_motor(sc):
    p, temp = sc.start[1], round(sc.temp)
    a, b = p > SAFE, temp < 50
    return a and b, (f"Pond 1 was {p}, so pollution(1) > 3 is {a}. The motor was {temp}°C, so motor_temp() < 50 "
                     f"is {b}. {a} and {b} is {a and b}")


def _tf_any(sc):
    a, b, cool = sc.start[1] > SAFE, sc.start[2] > SAFE, round(sc.temp) < 50
    return (a or b) and cool, (f"pollution(1) > 3 is {a} and pollution(2) > 3 is {b}, so the bracket ({a} or {b}) "
                               f"is {a or b}. The motor was {round(sc.temp)}°C, so motor_temp() < 50 is {cool}. "
                               f"{a or b} and {cool} is {(a or b) and cool}")


goal_tf_one = _truth_goal(_tf_one)
goal_tf_both = _truth_goal(_tf_both)
goal_tf_either = _truth_goal(_tf_either)
goal_truth = _truth_goal(_tf_motor)
goal_tf_any = _truth_goal(_tf_any)


def goal_cool_enough(sim, sc, ns, called):
    p, temp = sc.start[1], round(sc.temp)
    dirty, cool = p > SAFE, temp < 50
    want = dirty and cool
    why = (f"Pond 1 was {p}, so dirtier than 3 is {dirty}. The motor was {temp}°C, so below 50 is {cool}. "
           f"{dirty} and {cool} gives {want}")
    if want and not sim.ever_on:
        return False, f"{why}, so the motor should have gone on."
    if not want and sim.ever_on:
        return False, f"{why}, so the motor should have stayed off."
    return True, f"{why}, so the motor {'went on' if want else 'stayed off'}."


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
    if sc.start[1] <= SAFE:
        if sim.motor_hours == 0:
            return True, f"The pond was already clean ({sc.start[1]}), so the motor didn't need to run."
        return False, (f"The pond was already clean ({sc.start[1]}), but the motor ran for {sim.motor_hours} hours. "
                       "Check the pond before waiting, not after.")
    on = [t for t, what in sim.switches if what == "on"]
    if not on:
        return False, f"The pond was at {sc.start[1]}, but the motor never went on."
    offs = [t for t, what in sim.switches if what == "off" and t >= on[0]]
    if not offs:
        return False, "The motor never went off. Once the pond is 3 or below, call motor_off()."
    t = offs[0]
    if _p_at(sim, t) > SAFE:
        return False, (f"You switched off at {clock(t)}, when the pond was still {_p_at(sim, t)}. "
                       "Keep going while it's above 3.")
    if t >= 3 and _p_at(sim, t - 3) <= SAFE:
        return False, (f"The pond was already clean at {clock(t - 3)}, but the motor ran on until {clock(t)}. "
                       "Check the pond every 3 hours.")
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
# The task says what to achieve, not how. The page lists the pond functions a question uses ("uses"),
# because calling them isn't the Python skill being practised. Text can use `code` and **bold**.
# Each answer is what the page reveals and what check_scenario.py tests.
COOL = {"fire": "Check motor_temp() before switching on. If it's hot, switch off and wait while it cools."}
BLANK = ""   # questions start with an empty editor

LEVELS = [
    {
        "id": 1, "title": "How much room?", "topic": "calling a function",
        "uses": ["pollution"], "axis": 3,
        "task": ("Pond 1 is safe while its pollution is 3 or below. **How far below 3 is it?** Print the answer. "
                 "Your code is tested on two different mornings."),
        "starter": BLANK,
        "hint": "A function's result is a number, so you can do sums with it, e.g. `10 - pollution(1)`, and print the result.",
        "answer": "print(3 - pollution(1))\n",
        "cases": [
            Scenario("Monday", hours=3, ponds=1, start={1: 2.5}, after_code=0),
            Scenario("Tuesday", hours=3, ponds=1, start={1: 1.0}, after_code=0),
        ],
        "goal": goal_headroom,
    },
    {
        "id": 2, "title": "Is it getting worse?", "topic": "variables",
        "uses": ["pollution", "wait"], "axis": 3,
        "task": "Take two readings of pond 1, three hours apart, and **print how much the pollution went up**.",
        "starter": BLANK,
        "hint": "Keep each reading in a variable, e.g. `first = ...`, so you can subtract one from the other later.",
        "answer": (
            "first = pollution(1)\n"
            "wait(3)\n"
            "second = pollution(1)\n"
            "print(round(second - first, 1))\n"
        ),
        "cases": [Scenario("", hours=12, ponds=1, start={1: 2.4}, base=0.3, after_code=0)],
        "goal": goal_change,
    },
    {
        "id": 3, "title": "Four readings", "topic": "for loops",
        "uses": ["pollution", "wait"], "axis": 12,
        "task": ("Print a reading of pond 1 every 3 hours, **four times**. Write the reading code only once and "
                 "let a loop repeat it."),
        "starter": BLANK,
        "hint": "`for i in range(4):` repeats the indented lines underneath it 4 times. Watch `i` change.",
        "answer": (
            "for i in range(4):\n"
            "    print(pollution(1))\n"
            "    wait(3)\n"
        ),
        "cases": [Scenario("", hours=24, ponds=1, start={1: 2.0}, base=0.3, after_code=0)],
        "goal": goal_four,
    },
    {
        "id": 4, "title": "Keep them in a list", "topic": "lists",
        "uses": ["pollution", "wait"], "axis": 12,
        "task": ("Your code from question 3 is in the editor. Change it so the four readings are **kept in a list**, "
                 "then print the whole list once, at the end."),
        "starter": None,
        "hint": ("Start with an empty list before the loop, `readings = []`, and add to it inside the loop with "
                 "`readings.append(...)`."),
        "answer": (
            "readings = []\n"
            "\n"
            "for i in range(4):\n"
            "    readings.append(pollution(1))\n"
            "    wait(3)\n"
            "\n"
            "print(readings)\n"
        ),
        "cases": [Scenario("", hours=24, ponds=1, start={1: 2.0}, base=0.3, after_code=0)],
        "goal": goal_list,
    },
    {
        "id": 5, "title": "Highest and average", "topic": "lists",
        "uses": ["pollution", "wait"], "axis": 24,
        "task": ("A storm is due tonight. Your list code is in the editor: make it take readings for a whole day "
                 "(8 readings, 3 hours apart), then print the **highest** reading and the **average**."),
        "starter": None,
        "hint": "`max()`, `sum()` and `len()` all work on lists.",
        "answer": (
            "readings = []\n"
            "\n"
            "for i in range(8):\n"
            "    readings.append(pollution(1))\n"
            "    wait(3)\n"
            "\n"
            "print(max(readings))\n"
            "print(sum(readings) / len(readings))\n"
        ),
        "cases": [Scenario("", hours=30, ponds=1, start={1: 1.8}, spills={1: [(13.5, 1.5, 5.4)]}, after_code=0)],
        "goal": goal_log,
    },
    {
        "id": 6, "title": "Switch it on", "topic": "if",
        "uses": ["pollution", "motor_on"], "axis": 3,
        "task": ("The aerator cleans the pond but costs money to run. Switch it on **only if** pond 1 is "
                 "dirtier than 3. Your code is tested on three different mornings."),
        "starter": BLANK,
        "hint": "`if` runs the indented lines underneath it only when its condition is True.",
        "answer": (
            "if pollution(1) > 3:\n"
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
        "id": 7, "title": "Switch it off", "topic": "if",
        "uses": ["pollution", "motor_off"], "axis": 3,
        "task": ("Your switch-on code is in the editor. This time the aerator is already running: change the code "
                 "so it switches **off** if pond 1 is 3 or below, and keeps running if it isn't. Tested on three mornings."),
        "starter": None,
        "hint": "Flip the condition round. `<=` means \"less than or equal to\".",
        "answer": (
            "if pollution(1) <= 3:\n"
            "    motor_off()\n"
        ),
        "cases": [
            Scenario("Clean", hours=6, ponds=1, start={1: 2.0}, motor=True, after_code=3),
            Scenario("Murky", hours=6, ponds=1, start={1: 5.2}, motor=True, after_code=3),
            Scenario("Exactly 3", hours=6, ponds=1, start={1: 3.0}, motor=True, after_code=3),
        ],
        "goal": goal_switch_off,
    },
    {
        "id": 8, "title": "Danger, warning or ok", "topic": "elif",
        "uses": ["pollution"], "axis": 3,
        "task": "Print a status for pond 1: **danger** if it's above 6, **warning** if it's above 3, otherwise **ok**.",
        "starter": BLANK,
        "hint": "Use `if`, `elif` and `else`. Python stops at the first condition that's True, so order matters.",
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
        "id": 9, "title": "True or False?", "topic": "True and False",
        "uses": ["pollution"], "axis": 3,
        "task": ("A comparison is a question Python answers with **True** or **False**. Print whether pond 1 is "
                 "dirtier than 3: no `if`, just print the comparison. Tested on three mornings."),
        "starter": BLANK,
        "hint": "Try `print(5 > 3)` first: it prints True. Now put `pollution(1)` where the 5 is.",
        "answer": "print(pollution(1) > 3)\n",
        "cases": [
            Scenario("Dirty", hours=3, ponds=1, start={1: 5.0}, after_code=0),
            Scenario("Clean", hours=3, ponds=1, start={1: 2.0}, after_code=0),
            Scenario("Exactly 3", hours=3, ponds=1, start={1: 3.0}, after_code=0),
        ],
        "goal": goal_tf_one,
    },
    {
        "id": 10, "title": "Both clean?", "topic": "and",
        "uses": ["pollution"], "axis": 3,
        "task": ("Print whether pond 1 **and** pond 2 are both 3 or below: True or False. `and` is only True when "
                 "both sides are True. Tested on four mornings."),
        "starter": BLANK,
        "hint": ("Two comparisons joined by `and`, each one complete: `pollution(1) <= 3 and pollution(2) <= 3`. "
                 "Put the whole thing inside `print( )`."),
        "answer": "print(pollution(1) <= 3 and pollution(2) <= 3)\n",
        "cases": [
            Scenario("Both clean", hours=3, ponds=2, start={1: 2.1, 2: 2.8}, after_code=0),
            Scenario("Pond 2 dirty", hours=3, ponds=2, start={1: 2.1, 2: 4.6}, after_code=0),
            Scenario("Pond 1 dirty", hours=3, ponds=2, start={1: 4.6, 2: 2.1}, after_code=0),
            Scenario("Both dirty", hours=3, ponds=2, start={1: 4.6, 2: 5.2}, after_code=0),
        ],
        "goal": goal_tf_both,
    },
    {
        "id": 11, "title": "Either too high?", "topic": "or",
        "uses": ["pollution"], "axis": 3,
        "task": ("Your `and` code is in the editor. Change it to print whether pond 1 **or** pond 2 is above 6. "
                 "`or` is True when at least one side is True. Tested on four mornings."),
        "starter": None,
        "hint": "Swap `and` for `or`, and change both comparisons to `> 6`.",
        "answer": "print(pollution(1) > 6 or pollution(2) > 6)\n",
        "cases": [
            Scenario("Pond 1 high", hours=3, ponds=2, start={1: 6.8, 2: 2.0}, after_code=0),
            Scenario("Pond 2 high", hours=3, ponds=2, start={1: 2.0, 2: 6.8}, after_code=0),
            Scenario("Both high", hours=3, ponds=2, start={1: 7.1, 2: 6.8}, after_code=0),
            Scenario("Both below 6", hours=3, ponds=2, start={1: 4.0, 2: 5.0}, after_code=0),
        ],
        "goal": goal_tf_either,
    },
    {
        "id": 12, "title": "All clear?", "topic": "and in an if",
        "uses": ["pollution"], "axis": 3,
        "task": ("Now use `and` in an `if`. Print **all clear** if pond 1 and pond 2 are both 3 or below. If either "
                 "of them isn't, print **check ponds**."),
        "starter": BLANK,
        "hint": ("`and` is True only when the conditions on both sides are True. Each side needs its own "
                 "comparison: `one <= 3 and two <= 3`, not `one and two <= 3`."),
        "answer": (
            "one = pollution(1)\n"
            "two = pollution(2)\n"
            "\n"
            "if one <= 3 and two <= 3:\n"
            '    print("all clear")\n'
            "else:\n"
            '    print("check ponds")\n'
        ),
        "cases": [
            Scenario("Both clean", hours=3, ponds=2, start={1: 2.1, 2: 2.8}, after_code=0),
            Scenario("Pond 2 dirty", hours=3, ponds=2, start={1: 2.1, 2: 4.6}, after_code=0),
            Scenario("Pond 1 dirty", hours=3, ponds=2, start={1: 4.6, 2: 2.1}, after_code=0),
        ],
        "goal": goal_both_clean,
    },
    {
        "id": 13, "title": "Raise the alarm", "topic": "or",
        "uses": ["pollution"], "axis": 3,
        "task": ("Your all-clear code is in the editor. Change it to print **alarm** if pond 1 **or** pond 2 is above 6, "
                 "and **fine** if neither is."),
        "starter": None,
        "hint": ("`or` is True when at least one side is True. Like `and`, each side needs its own comparison: "
                 "`one > 6 or two > 6`."),
        "answer": (
            "one = pollution(1)\n"
            "two = pollution(2)\n"
            "\n"
            "if one > 6 or two > 6:\n"
            '    print("alarm")\n'
            "else:\n"
            '    print("fine")\n'
        ),
        "cases": [
            Scenario("Pond 1 high", hours=3, ponds=2, start={1: 6.8, 2: 2.0}, after_code=0),
            Scenario("Pond 2 high", hours=3, ponds=2, start={1: 2.0, 2: 6.8}, after_code=0),
            Scenario("Both below 6", hours=3, ponds=2, start={1: 4.0, 2: 5.0}, after_code=0),
        ],
        "goal": goal_alarm,
    },
    {
        "id": 14, "title": "Which pond?", "topic": "comparing values",
        "uses": ["pollution", "switch_to", "motor_on"], "axis": 9,
        "task": "Two ponds, one air hose. Clean **whichever pond is dirtier**.",
        "starter": BLANK,
        "hint": "Read both ponds into variables, compare them with `if ... > ...:`, and move the hose before switching on.",
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
        "id": 15, "title": "Wait for the storm", "topic": "while loops",
        "uses": ["pollution", "wait", "motor_on"], "axis": 24,
        "task": ("A storm is on its way, but nobody knows when. Switch the motor on **as soon as** pond 1 gets "
                 "dirtier than 3, and not before."),
        "starter": BLANK,
        "hint": "A `while` loop keeps repeating as long as its condition is True. What should it repeat while the pond is still clean?",
        "answer": (
            "while pollution(1) <= 3:\n"
            "    wait(3)\n"
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
        "id": 16, "title": "Stop when it's clean", "topic": "while loops",
        "uses": ["pollution", "wait", "motor_on", "motor_off"], "axis": 6,
        "task": ("Your storm code is in the editor. Now turn it round: run the motor on pond 1 until the pond is 3 or "
                 "below, then **switch it off** straight away. Sometimes the pond is clean already."),
        "starter": None,
        "hint": "This time the loop should keep going while the pond is still dirty. What goes after the loop?",
        "answer": (
            "motor_on()\n"
            "\n"
            "while pollution(1) > 3:\n"
            "    wait(3)\n"
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
        "id": 17, "title": "Keep watch", "topic": "while True",
        "uses": ["pollution", "motor_on", "motor_off", "wait"],
        "task": ("Two days of storms. Every 3 hours, check pond 1: motor on if it's dirtier than 3, off if it isn't. "
                 "**Keep the fish alive.**"),
        "starter": BLANK,
        "hint": "`while True:` repeats forever (here, until the two days are up). Put the check and a `wait(3)` inside it.",
        "answer": (
            "while True:\n"
            "    if pollution(1) > 3:\n"
            "        motor_on()\n"
            "    else:\n"
            "        motor_off()\n"
            "    wait(3)\n"
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
        "id": 18, "title": "Cool motor?", "topic": "True, False and and",
        "uses": ["pollution", "motor_temp"], "axis": 3,
        "task": ("No `if` yet. **Print** whether pond 1 is dirtier than 3 **and** the motor is below 50°C, and Python "
                 "answers **True** or **False**. Tested on four mornings."),
        "starter": BLANK,
        "hint": ("A comparison is a question with a True/False answer: `print(5 > 3)` prints True. `and` joins two of "
                 "them, and is True only when both are True."),
        "answer": "print(pollution(1) > 3 and motor_temp() < 50)\n",
        "cases": [
            Scenario("Dirty, cool motor", hours=3, ponds=1, start={1: 5.0}, temp=30, after_code=0),
            Scenario("Dirty, hot motor", hours=3, ponds=1, start={1: 5.0}, temp=75, after_code=0),
            Scenario("Clean, cool motor", hours=3, ponds=1, start={1: 2.0}, temp=30, after_code=0),
            Scenario("Clean, hot motor", hours=3, ponds=1, start={1: 2.0}, temp=75, after_code=0),
        ],
        "goal": goal_truth,
    },
    {
        "id": 19, "title": "Cool enough?", "topic": "and",
        "uses": ["pollution", "motor_temp", "motor_on"], "axis": 3,
        "task": ("Your True/False code is in the editor. Now act on it: switch the motor on only if pond 1 is dirtier "
                 "than 3 **and** the motor is below 50°C. (It catches fire at 100°C.)"),
        "starter": None,
        "hint": "Put the condition after `if` instead of inside `print( )`, and switch the motor on underneath.",
        "answer": (
            "if pollution(1) > 3 and motor_temp() < 50:\n"
            "    motor_on()\n"
        ),
        "cases": [
            Scenario("Dirty, cool motor", hours=6, ponds=1, start={1: 5.0}, temp=30, after_code=3),
            Scenario("Dirty, hot motor", hours=6, ponds=1, start={1: 5.0}, temp=75, after_code=3),
            Scenario("Clean, cool motor", hours=6, ponds=1, start={1: 2.0}, temp=30, after_code=3),
        ],
        "advice": {"fire": "The motor was already hot, so it should have stayed off. With and, both sides have to be True."},
        "goal": goal_cool_enough,
    },
    {
        "id": 20, "title": "Any pond need it?", "topic": "or and and together",
        "uses": ["pollution", "motor_temp"], "axis": 3,
        "task": ("Two ponds, one motor. Print whether the motor should run: True if pond 1 **or** pond 2 is dirtier "
                 "than 3, **and** the motor is below 50°C. Tested on four mornings."),
        "starter": BLANK,
        "hint": ("Work out the `or` part first by putting it in brackets: `(... > 3 or ... > 3) and ... < 50`. "
                 "Without the brackets, Python does the `and` first."),
        "answer": "print((pollution(1) > 3 or pollution(2) > 3) and motor_temp() < 50)\n",
        "cases": [
            Scenario("Pond 1 dirty, cool motor", hours=3, ponds=2, start={1: 5.0, 2: 2.0}, temp=30, after_code=0),
            Scenario("Pond 2 dirty, cool motor", hours=3, ponds=2, start={1: 2.0, 2: 5.0}, temp=30, after_code=0),
            Scenario("Both clean, cool motor", hours=3, ponds=2, start={1: 2.0, 2: 2.5}, temp=30, after_code=0),
            Scenario("Pond 1 dirty, hot motor", hours=3, ponds=2, start={1: 5.0, 2: 2.0}, temp=75, after_code=0),
        ],
        "goal": goal_tf_any,
    },
    {
        "id": 21, "title": "Too hot", "topic": "nested ifs and loops",
        "uses": ["pollution", "motor_temp", "motor_on", "motor_off", "wait"], "carry": 17,
        "task": ("A long storm. Run this code and watch the motor: it heats up 15°C an hour while running and catches "
                 "fire at 100°C. **Change it** so the motor rests and cools down whenever it gets hot."),
        "starter": (
            "while True:\n"
            "    if pollution(1) > 3:\n"
            "        motor_on()\n"
            "    else:\n"
            "        motor_off()\n"
            "    wait(3)\n"
        ),
        "hint": ("Before switching on, check `motor_temp()`. If it's hot, switch off and keep waiting while it's still "
                 "warm. An `if` inside an `if`, and a `while` inside that, is fine."),
        "answer": (
            "while True:\n"
            "    if pollution(1) > 3:\n"
            "        if motor_temp() > 50:\n"
            "            motor_off()\n"
            "            while motor_temp() > 20:\n"
            "                wait(3)\n"
            "        else:\n"
            "            motor_on()\n"
            "            wait(3)\n"
            "    else:\n"
            "        motor_off()\n"
            "        wait(3)\n"
        ),
        "advice": dict(COOL, fish="The motor has to run as much as it safely can. Did it spend too long cooling?"),
        "cases": [Scenario("", hours=48, ponds=1, start={1: 1.5}, spills={1: [(14, 5, 14.0)]})],
        "goal": goal_survive,
    },
    {
        "id": 22, "title": "Your own function", "topic": "def",
        "uses": ["pollution"], "axis": 3,
        "task": ("Write a function called `report` that takes a pond number and prints that pond's pollution. "
                 "Then use it for **both ponds**."),
        "starter": BLANK,
        "hint": "`def report(pond):` starts the function. Inside it, `pond` is whatever number you called it with.",
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
        "id": 23, "title": "Two ponds", "topic": "functions and loops",
        "uses": ["pollution", "motor_temp", "motor_on", "motor_off", "switch_to", "wait"],
        "task": ("Look after both ponds for two days. Write a function `clean(pond)` that cleans one pond until it's "
                 "safe, without overheating the motor, and use it for both ponds over and over."),
        "starter": BLANK,
        "hint": ("Inside `clean`: move the hose there, then a `while` loop like question 16 with your cool-down from "
                 "question 21. Switch the motor off at the end: the hose can only move when it's off."),
        "answer": (
            "def clean(pond):\n"
            "    switch_to(pond)\n"
            "    while pollution(pond) > 3:\n"
            "        if motor_temp() > 50:\n"
            "            motor_off()\n"
            "            while motor_temp() > 20:\n"
            "                wait(3)\n"
            "        else:\n"
            "            motor_on()\n"
            "            wait(3)\n"
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
        "id": 24, "title": "Pond Rescue", "topic": "the full challenge",
        "uses": ["pollution", "motor_temp", "motor_on", "motor_off", "switch_to", "wait"], "carry": 23,
        "bonus": True,
        "task": ("Four days, two ponds, three storms, and on day 3 a barrel of chemicals falls into pond 1 and keeps "
                 "leaking. Keep every fish alive without setting the motor on fire. **Bonus:** use the motor for as "
                 "few hours as you can."),
        "starter": BLANK,
        "hint": ("Your question 23 code is a good start. If a pond dies, look at the chart: was the motor cooling "
                 "down, or busy at the other pond? The toxic leak keeps going, so don't leave pond 1 too early."),
        "answer": (
            "while True:\n"
            "    for pond in [1, 2]:\n"
            "        switch_to(pond)\n"
            "        while pollution(pond) > 3:\n"
            "            if motor_temp() > 50:\n"
            "                motor_off()\n"
            "                while motor_temp() > 20:\n"
            "                    wait(3)\n"
            "            else:\n"
            "                motor_on()\n"
            "                wait(3)\n"
            "        motor_off()\n"
        ),
        "advice": dict(COOL, fish="Look at the chart: when the fish died, was the motor cooling down, or busy at the other pond?"),
        "cases": [Scenario("", hours=HOURS, ponds=2, start=START_POLLUTION, spills=SPILLS, toxic=TOXIC)],
        "goal": goal_final,
    },
]
# a starter of None means: start from the previous question's answer (and offer the student's own code)
for _i, _lv in enumerate(LEVELS):
    if _lv["starter"] is None:
        _lv["starter"] = LEVELS[_i - 1]["answer"]
        _lv.setdefault("carry", LEVELS[_i - 1]["id"])

# ---------------- worked examples ----------------
# Shown before the question they lead into: ready-made code with comments. Students press Run and watch;
# there's nothing to pass. They introduce each pond function and each new bit of Python.
def goal_demo(sim, sc, ns, called):
    return True, "That's the example. Look back through the output and the variables, then try the next question."


def _demo(n, title, uses, task, code, case):
    return {"id": 100 + n, "demo": True, "title": title, "topic": "example", "uses": uses, "task": task,
            "starter": code, "hint": "", "answer": code, "cases": [case], "goal": goal_demo}


DEMOS = [   # (question number, the example shown just before it), in order
    (1, _demo(1, "The sensor and the clock", ["pollution", "wait"],
             "Press **Run** and watch the sensor in the pond. Each line has a comment (after the #) saying what it does.",
             "# pollution(1) checks the pollution in pond 1\n"
             "pollution(1)\n"
             "\n"
             "# wait(3) lets three hours pass\n"
             "wait(3)\n"
             "\n"
             "# so we can check the pollution again, three hours later\n"
             "pollution(1)\n",
             Scenario("", hours=6, ponds=1, start={1: 2.0}, base=0.3, after_code=0))),
    (3, _demo(2, "A loop", ["pollution", "wait"],
             "Press **Run** and watch `i` in the Variables panel as the loop goes round.",
             "# a for loop repeats the indented lines underneath it\n"
             "# range(3) counts 0, 1, 2, and i is the count each time round\n"
             "for i in range(3):\n"
             "    print(\"Time round the loop:\", i)\n"
             "    pollution(1)\n"
             "    wait(3)\n"
             "\n"
             "# this line isn't indented, so it runs once, after the loop\n"
             "print(\"Finished\")\n",
             Scenario("", hours=12, ponds=1, start={1: 2.0}, base=0.3, after_code=0))),
    (4, _demo(3, "A list", ["pollution"],
             "Press **Run** and watch the list grow in the Variables panel.",
             "# [] is an empty list\n"
             "numbers = []\n"
             "\n"
             "# append adds something to the end of the list\n"
             "numbers.append(2.5)\n"
             "numbers.append(3.1)\n"
             "numbers.append(pollution(1))\n"
             "print(numbers)\n"
             "\n"
             "# max, sum and len all work on a list\n"
             "print(max(numbers))\n"
             "print(sum(numbers))\n"
             "print(len(numbers))\n",
             Scenario("", hours=3, ponds=1, start={1: 2.2}, after_code=0))),
    (6, _demo(4, "The aerator", ["motor_on", "motor_off", "wait"],
             "Meet the aerator. Press **Run** and watch the bubbles and the pond's colour.",
             "# motor_on() starts the aerator. It pumps air into the pond and cleans it\n"
             "motor_on()\n"
             "wait(3)\n"
             "\n"
             "# motor_off() stops it again\n"
             "motor_off()\n"
             "wait(3)\n",
             Scenario("", hours=6, ponds=1, start={1: 5.5}, after_code=0))),
    (6, _demo(5, "if", ["pollution"],
               "Press **Run**, then change the 3 to a 5 and run it again. What changes?",
               "# the indented line only runs if the condition is True\n"
               "if pollution(1) > 3:\n"
               "    print(\"Pond 1 is dirty\")\n"
               "\n"
               "# this line isn't indented, so it always runs\n"
               "print(\"Checked\")\n",
               Scenario("", hours=3, ponds=1, start={1: 4.2}, after_code=0))),
    (9, _demo(6, "True and False", [],
             "Press **Run**. Each line prints Python's answer: True or False.",
             "# a comparison is a question Python answers with True or False\n"
             "print(5 > 3)\n"
             "print(2 > 3)\n"
             "\n"
             "# and is True only if both sides are True\n"
             "print(5 > 3 and 2 > 3)\n"
             "\n"
             "# or is True if either side is True\n"
             "print(5 > 3 or 2 > 3)\n",
             Scenario("", hours=3, ponds=1, start={1: 2.0}, after_code=0))),
    (14, _demo(7, "Moving the hose", ["switch_to", "motor_on", "motor_off", "wait"],
              "One aerator, two ponds. Press **Run** and watch the hose.",
              "# switch_to(2) moves the air hose to pond 2. It takes 3 hours\n"
              "switch_to(2)\n"
              "\n"
              "# now the aerator cleans pond 2\n"
              "motor_on()\n"
              "wait(3)\n"
              "\n"
              "# switch the motor off before moving the hose again!\n"
              "motor_off()\n",
              Scenario("", hours=9, ponds=2, start={1: 2.0, 2: 5.5}, after_code=0))),
    (15, _demo(8, "A while loop", ["wait"],
              "Press **Run** and watch `hours` in the Variables panel.",
              "# a while loop keeps repeating as long as its condition is True\n"
              "hours = 0\n"
              "while hours < 9:\n"
              "    wait(3)\n"
              "    hours = hours + 3\n"
              "    print(hours, \"hours have passed\")\n"
              "\n"
              "# once hours < 9 is False, the loop stops and this runs\n"
              "print(\"Done\")\n",
              Scenario("", hours=12, ponds=1, start={1: 2.0}, base=0.2, after_code=0))),
    (18, _demo(9, "The motor's temperature", ["motor_temp", "motor_on", "motor_off", "wait"],
              "Press **Run** and watch the thermometer.",
              "# motor_temp() reads the motor's temperature in °C\n"
              "print(motor_temp())\n"
              "\n"
              "# it heats up while the motor runs...\n"
              "motor_on()\n"
              "wait(3)\n"
              "print(motor_temp())\n"
              "\n"
              "# ...and cools down when it's off. At 100°C it catches fire\n"
              "motor_off()\n"
              "wait(3)\n"
              "print(motor_temp())\n",
              Scenario("", hours=6, ponds=1, start={1: 4.0}, after_code=0))),
    (22, _demo(10, "Your own function", ["pollution"],
              "Press **Run** and watch `pond` in the Variables panel each time the function runs.",
              "# def makes a function of your own. pond is whatever number you give it\n"
              "def check(pond):\n"
              "    print(\"Pond\", pond, \"is at\", pollution(pond))\n"
              "\n"
              "# now use it, as many times as you like\n"
              "check(1)\n"
              "check(2)\n",
              Scenario("", hours=3, ponds=2, start={1: 4.2, 2: 1.9}, after_code=0))),
]
for _q, _d in DEMOS:
    LEVELS.insert(next(i for i, lv in enumerate(LEVELS) if lv["id"] == _q), _d)
LEVELS_BY_ID = {lv["id"]: lv for lv in LEVELS}
FINAL_LEVEL = LEVELS[-1]["id"]


def level_for_page(lv):
    """The parts of a question the page needs before Python has loaded (build.py writes them into the page)."""
    first = lv["cases"][0]
    return {
        "id": lv["id"], "title": lv["title"], "topic": lv["topic"], "uses": lv["uses"], "task": lv["task"],
        "starter": lv["starter"], "hint": lv["hint"], "answer": lv["answer"],
        "carry": lv.get("carry"), "bonus": lv.get("bonus", False), "demo": lv.get("demo", False),
        "storm": any(sc.toxic or any(sc.spills.values()) for sc in lv["cases"]),
        "tests": [sc.name for sc in lv["cases"]] if len(lv["cases"]) > 1 else [],
        "ponds": len(first.ponds), "hours": first.hours, "axis": lv.get("axis"), "preview": Sim(first).frames[0],
    }
