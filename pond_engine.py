import math
import sys
import json

# ---------------- scenario settings ----------------
HOURS = 96            # 4 days, 1 hour per animation second
AMBIENT = 15.0        # motor cools down to this
START_TEMP = 20.0
HEAT_PER_HOUR = 15.0  # motor running
COOL_PER_HOUR = 8.0   # motor off
FIRE_TEMP = 100.0
SAFE = 3.0
DEADLY = 8.0
AERATE = 1.5          # pollution removed per hour by a running aerator
SWITCH_HOURS = 3      # swapping the air hose to the other pond takes this long
DECAY = 0.03          # natural clean-up per hour (fraction)
BASE_INFLOW = 0.045   # background pollution per hour
START_POLLUTION = {1: 1.5, 2: 1.5}

# spills: (centre hour, width in hours, total pollution added)
SPILLS = {
    1: [(18, 6, 12.0)],
    2: [(38, 5, 12.0), (62, 6, 8.0)],
}


# toxic spills: (hour, pond, instant jump, total that leaks out of the barrel afterwards, hours until the leak is worst)
TOXIC = [(52, 1, 1.5, 16.0, 8.0)]


def sewage_inflow(pond, t):
    total = BASE_INFLOW
    for c, s, a in SPILLS[pond]:
        total += a / (s * math.sqrt(2 * math.pi)) * math.exp(-0.5 * ((t + 0.5 - c) / s) ** 2)
    return total


def toxic_inflow(pond, t):
    total = 0.0
    for h, p, jump, leak, tau in TOXIC:
        if p == pond and t >= h:
            x = t + 0.5 - h
            total += leak * x / tau ** 2 * math.exp(-x / tau)
    return total


def inflow(pond, t):
    return sewage_inflow(pond, t) + toxic_inflow(pond, t)


class _SimOver(Exception):
    pass


class _Sprayed(Exception):
    pass


class _TimeFrozen(Exception):
    pass


class PondError(Exception):
    """Mistakes in how the built-in functions are used."""


class Sim:
    def __init__(self):
        self.t = 0
        self.P = dict(START_POLLUTION)
        self.temp = START_TEMP
        self.motor = False
        self.target = 1
        self.motor_dead = False
        self.fish_dead = {1: None, 2: None}
        self.motor_hours = 0
        self.switching = False
        self.frames = []
        self.events = []
        self.prints = []
        self.lines_since_tick = 0
        self.calls_since_tick = 0
        self._snapshot()

    # ---- recording ----
    def _snapshot(self):
        self.frames.append({
            "t": self.t,
            "p1": round(self.P[1], 3),
            "p2": round(self.P[2], 3),
            "temp": round(self.temp, 2),
            "motor": self.motor,
            "target": self.target,
            "dead1": self.fish_dead[1] is not None,
            "dead2": self.fish_dead[2] is not None,
            "fire": self.motor_dead,
            "switching": self.switching,
            "in1": round(sewage_inflow(1, self.t), 3),
            "in2": round(sewage_inflow(2, self.t), 3),
            "tx1": round(toxic_inflow(1, self.t), 3),
            "tx2": round(toxic_inflow(2, self.t), 3),
        })

    def _update_snapshot(self):
        # actions taken at the current hour change what the animation shows for it
        self.frames.pop()
        self._snapshot()

    def event(self, kind, text):
        self.events.append({"t": self.t, "kind": kind, "text": text})

    # ---- physics ----
    def hour(self):
        running = self.motor and not self.motor_dead
        for h, p, jump, leak, tau in TOXIC:
            if h == self.t:
                self.P[p] += jump
                self.event("toxic", f"Toxic spill! A barrel of chemicals fell into pond {p}.")
        for p in (1, 2):
            aer = AERATE if (running and self.target == p) else 0.0
            self.P[p] = max(0.0, self.P[p] + inflow(p, self.t) - DECAY * self.P[p] - aer)
        if running:
            self.temp += HEAT_PER_HOUR
            self.motor_hours += 1
        else:
            self.temp = max(AMBIENT, self.temp - COOL_PER_HOUR)
        self.t += 1
        for p in (1, 2):
            if self.fish_dead[p] is None and self.P[p] > DEADLY:
                self.fish_dead[p] = self.t
                self.event("fish", f"Pond {p}: pollution passed {DEADLY:g}. The fish didn't make it.")
        if running and self.temp >= FIRE_TEMP:
            self.motor_dead = True
            self.motor = False
            self.event("fire", f"The motor hit {FIRE_TEMP:g}°C and caught fire!")
        self.lines_since_tick = 0
        self.calls_since_tick = 0
        self._snapshot()
        if self.t >= HOURS:
            raise _SimOver()

    def tick_call(self):
        self.calls_since_tick += 1
        if self.calls_since_tick > 20000:
            raise _TimeFrozen()


def _check_pond(pond, fname):
    if pond not in (1, 2):
        raise PondError(f"{fname}({pond!r}): there are only ponds 1 and 2.")


def make_builtins(sim):
    def pollution(pond):
        """Pollution in pond 1 or 2. Safe below 3, fish die above 8."""
        _check_pond(pond, "pollution")
        sim.tick_call()
        return round(sim.P[pond], 1)

    def motor_temp():
        """Motor temperature in °C. It catches fire at 100."""
        sim.tick_call()
        return round(sim.temp)

    def motor_on():
        """Switch the motor on."""
        sim.tick_call()
        if sim.motor_dead:
            return
        if not sim.motor:
            sim.motor = True
            sim._update_snapshot()

    def motor_off():
        """Switch the motor off."""
        sim.tick_call()
        if sim.motor:
            sim.motor = False
            sim._update_snapshot()

    def switch_to(pond):
        """Send the motor's air to pond 1 or 2. The motor must be off."""
        _check_pond(pond, "switch_to")
        sim.tick_call()
        if pond == sim.target:
            return
        if sim.motor and not sim.motor_dead:
            sim.target = pond
            sim._update_snapshot()
            sim.event("spray", "You switched the air hose with the motor running. It whipped round and soaked the farmer!")
            raise _Sprayed()
        sim.target = pond
        sim.switching = True
        sim._update_snapshot()
        try:
            for _ in range(SWITCH_HOURS):
                if _ == SWITCH_HOURS - 1:
                    sim.switching = False
                sim.hour()
        finally:
            sim.switching = False

    def wait(hours=3):
        """Let time pass. Sensors only update every 3 hours, so use wait() or wait(6), wait(9)..."""
        if not isinstance(hours, int) or isinstance(hours, bool) or hours <= 0 or hours % 3 != 0:
            raise PondError(f"wait({hours!r}): the sensors only update every 3 hours, so use wait(), wait(6), wait(9)...")
        for _ in range(hours):
            sim.hour()

    return {
        "pollution": pollution,
        "motor_temp": motor_temp,
        "motor_on": motor_on,
        "motor_off": motor_off,
        "switch_to": switch_to,
        "wait": wait,
    }


class _PrintCatcher:
    def __init__(self, sim):
        self.sim = sim
        self.buf = ""

    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            if len(self.sim.prints) < 500:
                self.sim.prints.append({"t": self.sim.t, "text": line})
        return len(s)

    def flush(self):
        if self.buf:
            if len(self.sim.prints) < 500:
                self.sim.prints.append({"t": self.sim.t, "text": self.buf})
            self.buf = ""


USER_FILE = "<your code>"
LINE_LIMIT = 300000


def run_user_code(code):
    sim = Sim()
    result = {"outcome": None, "error": None, "error_line": None}
    ns = {"__name__": "__main__"}
    ns.update(make_builtins(sim))

    try:
        compiled = compile(code, USER_FILE, "exec")
    except SyntaxError as e:
        result["outcome"] = "error"
        msg = e.msg
        if "unindent" in msg or "indent" in msg:
            msg += " (check the spaces at the start of the line)"
        result["error"] = f"SyntaxError: {msg}"
        result["error_line"] = e.lineno
        return _pack(sim, result, finish=False)

    def local_tracer(frame, event, arg):
        if event == "line":
            sim.lines_since_tick += 1
            if sim.lines_since_tick > LINE_LIMIT:
                raise _TimeFrozen()
        return local_tracer

    def global_tracer(frame, event, arg):
        if frame.f_code.co_filename == USER_FILE:
            return local_tracer
        return None

    old_stdout = sys.stdout
    catcher = _PrintCatcher(sim)
    sys.stdout = catcher
    finish = True
    try:
        sys.settrace(global_tracer)
        try:
            exec(compiled, ns)
        finally:
            sys.settrace(None)
    except _SimOver:
        pass
    except _Sprayed:
        result["outcome"] = "sprayed"
        finish = False
    except _TimeFrozen:
        result["outcome"] = "frozen"
        result["error"] = ("Time stopped! Your code is going round a loop without ever calling wait(), "
                           "so no time passes. Add a wait() inside the loop.")
        sim.event("frozen", "Time stopped! No wait() in your loop.")
        finish = False
    except PondError as e:
        result["outcome"] = "error"
        result["error"] = str(e)
        result["error_line"] = _user_line(e)
        finish = False
    except RecursionError as e:
        result["outcome"] = "error"
        result["error"] = "RecursionError: a function keeps calling itself."
        result["error_line"] = _user_line(e)
        finish = False
    except Exception as e:  # student mistakes: NameError, TypeError, ...
        result["outcome"] = "error"
        result["error"] = f"{type(e).__name__}: {e}"
        result["error_line"] = _user_line(e)
        finish = False
    finally:
        catcher.flush()
        sys.stdout = old_stdout

    if result["error_line"] is not None and result["outcome"] == "error":
        sim.event("error", f"Your code crashed on line {result['error_line']}.")
    return _pack(sim, result, finish=finish)


def _user_line(exc):
    tb = exc.__traceback__
    line = None
    while tb is not None:
        if tb.tb_frame.f_code.co_filename == USER_FILE:
            line = tb.tb_lineno
        tb = tb.tb_next
    return line


def _pack(sim, result, finish):
    if finish and sim.t < HOURS:
        # code finished early: the pond carries on with the motor as it was left
        try:
            while sim.t < HOURS:
                sim.hour()
        except _SimOver:
            pass
    if result["outcome"] is None:
        alive = [p for p in (1, 2) if sim.fish_dead[p] is None]
        result["outcome"] = "win" if len(alive) == 2 else "lose"
    result["fish_dead"] = sim.fish_dead
    result["motor_hours"] = sim.motor_hours
    result["motor_dead"] = sim.motor_dead
    result["hours"] = sim.t
    return json.dumps({
        "frames": sim.frames,
        "events": sim.events,
        "prints": sim.prints,
        "result": result,
        "settings": {"hours": HOURS, "safe": SAFE, "deadly": DEADLY, "fire": FIRE_TEMP},
    })
