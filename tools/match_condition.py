#!/usr/bin/env python3
"""
match_condition.py — the career's players, as they are TODAY, into the match.

Every career club is a real eFootball club, so every fixture is compiled onto the game's own team
records (play_match.real_slot_match) — real faces, kits and badges. That path wrote the XI order,
shirts, the armband and the roles, and nothing else: a player's 26 abilities stayed exactly as
Konami shipped them. Three seasons of training, a teenager's growth, a veteran's decline, a squad
run into the ground by fixture congestion — none of it reached the pitch. This module is the
missing half of the compile.

Three things, all per-match (the working tree is a fresh copy of the base every time, so nothing
accumulates and the database is never written):

  1. WHO PLAYS. A player who is injured or suspended for this fixture cannot start: he is swapped
     for the best available man on the bench in his position group, and every unavailable player
     goes to the back of the squad order, outside the matchday squad when the club has the numbers.

  2. HOW GOOD HE IS NOW. The career's own player_attributes are written over the game's.

  3. HOW HE IS TODAY. Fatigue, form and morale take a share of his HEADROOM ABOVE 40 — never a
     multiply of the raw value (ruling 2026-08-24). Abilities are a 6-bit field storing value-40,
     so 40 is the floor of the scale: 45 x 0.8 = 36 cannot be stored and would clamp back to 40
     (the weakest players would never tire), while 85 x 0.8 loses 17 points. Shaving headroom costs
     everyone the same fraction of his ability: at the same tiredness 85 -> 76 and 50 -> 48.
     Condition only ever takes away. The good day is the game's own Condition arrow.

The write itself goes through the verified field map (tools/data/player_layouts.json, every ability
proven exact against the game's export) and is gated twice: a record may change ONLY inside its 26
ability fields, and every value written must read back as the value asked for. Anything else raises
and the compile stops before a byte reaches the game.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LAYOUTS = REPO / "tools" / "data" / "player_layouts.json"

FLOOR, CEILING = 40, 99
MAX_FATIGUE = 60                    # ML.Core ConditionModel.MaxFatigue
NEUTRAL_FORM, FORM_SPAN = 6.5, 2.5  # form runs 4.0 .. 9.0 around 6.5
NEUTRAL_MORALE = 50                 # morale runs 0 .. 100

# What tiredness costs. The sim takes fatigue/12 rating points off a side (5 at the ceiling);
# these land an 85-rated player about the same distance down, with the legs going first.
GENERAL_TIRED = 0.08                # share of headroom every ability loses at full fatigue
PHYSICAL_TIRED = 0.20               # ...and the further share the legs lose
LOW_MOOD = 0.10                     # share lost at rock-bottom form and morale together
PHYSICAL = ("stamina", "speed", "acceleration")

_GROUP = {"GK": "GK", "CB": "DEF", "LB": "DEF", "RB": "DEF", "DMF": "MID", "CMF": "MID", "LMF": "MID",
          "RMF": "MID", "AMF": "MID", "LWF": "FWD", "RWF": "FWD", "SS": "FWD", "CF": "FWD"}


class CompileRefused(Exception):
    """A gate failed. Nothing may be installed from this working tree."""


# ------------------------------------------------------------------------------------ condition

def condition_factors(fatigue: float, form: float, morale: float) -> tuple[float, float]:
    """(general, physical): the share of his headroom above 40 a player keeps today. Both <= 1."""
    tired = min(max(fatigue / MAX_FATIGUE, 0.0), 1.0)
    mood = min(max((form - NEUTRAL_FORM) / FORM_SPAN, -1.0), 1.0)
    spirit = min(max((morale - NEUTRAL_MORALE) / 50.0, -1.0), 1.0)
    low = min(max(-(0.6 * mood + 0.4 * spirit), 0.0), 1.0)      # only a BAD patch costs anything
    general = (1.0 - GENERAL_TIRED * tired) * (1.0 - LOW_MOOD * low)
    return general, general * (1.0 - PHYSICAL_TIRED * tired)


def for_the_match(abilities: dict[str, int], fatigue: float = 0, form: float = NEUTRAL_FORM,
                  morale: float = NEUTRAL_MORALE) -> dict[str, int]:
    """His abilities for THIS fixture: new = 40 + round((old - 40) * factor), clamped to 40..99."""
    general, physical = condition_factors(fatigue, form, morale)
    out = {}
    for name, value in abilities.items():
        factor = physical if name in PHYSICAL else general
        shaved = FLOOR + round((max(FLOOR, int(value)) - FLOOR) * factor)
        out[name] = min(max(shaved, FLOOR), CEILING)
    return out


# ------------------------------------------------------------------------------------ who plays

def order_for_availability(players: list[dict]) -> tuple[list[dict], list[str]]:
    """The squad in compile order with nobody unavailable in the XI.

    players is in DB slot order (0..10 = the XI, in formation-slot order) and each carries
    'unavailable' (a reason, or None). An unavailable starter is replaced IN PLACE — his
    formation slot keeps an occupant, so nobody else shifts position — by the best available
    bench player in his position group, then by the best available man of any kind. Every
    unavailable player then goes to the back of the order. Returns (order, what was changed)."""
    order = list(players)
    notes: list[str] = []
    for i in range(min(11, len(order))):
        out = order[i]
        if not out.get("unavailable"):
            continue
        bench = [j for j in range(11, len(order)) if not order[j].get("unavailable")]
        if not bench:
            notes.append(f"{out['name']} is {out['unavailable']} and there is nobody fit to replace him")
            continue
        want = _GROUP.get(out.get("position") or "", "MID")
        same = [j for j in bench if _GROUP.get(order[j].get("position") or "", "MID") == want]
        pick = max(same or bench, key=lambda j: order[j].get("overall") or 0)
        order[i], order[pick] = order[pick], order[i]
        notes.append(f"{out['name']} is {out['unavailable']}: {order[i]['name']} starts in his place")
    fit_bench = [p for p in order[11:] if not p.get("unavailable")]
    out_bench = [p for p in order[11:] if p.get("unavailable")]
    return order[:11] + fit_bench + out_bench, notes


# ------------------------------------------------------------------------------------ the write

class AbilityWriter:
    """Write display-scale abilities (what the app stores, what the game shows) into Player.bin
    records of one layout. The file does not store the displayed number: below pid 2^32 the 6-bit
    field holds a value the game scales by 24/25, so writing a display value means choosing the
    stored value that SHOWS as it — the one nearest what is there now, so a record whose
    abilities have not changed is never touched at all."""

    def __init__(self, stride: int = 400):
        layouts = json.loads(LAYOUTS.read_text(encoding="utf-8"))["layouts"]
        layout = layouts.get(str(stride))
        if layout is None:
            raise CompileRefused(f"Player.bin uses a {stride}-byte record this writer has no field map for — "
                                 "a game update changed the format. Abilities are not written.")
        bad = set(layout.get("unverified", []))
        self.stride = stride
        self.offsets = {k: off for k, off in layout["abilities"].items() if k not in bad}
        disp = layout["ability_display"]
        self.unscaled_from, self.num, self.den = disp["unscaled_from_pid"], disp["num"], disp["den"]
        self.floor = disp["floor"]
        self.mask = 0
        for off in self.offsets.values():
            self.mask |= 0x3F << off

    def shown(self, stored: int, pid: int) -> int:
        """What the game shows for a stored value (field + 40). Mirrors game_world.PlayerDecoder."""
        if pid >= self.unscaled_from:
            return stored
        return max(self.floor, int(stored * self.num / self.den + 0.5))

    def _stored_for(self, target: int, pid: int, current: int) -> int:
        options = [s for s in range(40, 104) if self.shown(s, pid) == target]
        if not options:
            raise CompileRefused(f"no stored value shows as {target} (pid {pid})")
        return min(options, key=lambda s: (abs(s - current), s))

    def read(self, rec: bytes, pid: int) -> dict[str, int]:
        v = int.from_bytes(rec, "little")
        return {k: self.shown(((v >> off) & 0x3F) + 40, pid) for k, off in self.offsets.items()}

    def apply(self, rec: bytearray, pid: int, targets: dict[str, int]) -> int:
        """Bring one record's abilities to `targets` (display scale). Returns fields changed."""
        before = int.from_bytes(rec, "little")
        v = before
        changed = 0
        wanted = {}
        for name, off in self.offsets.items():
            if name not in targets:
                continue
            target = min(max(int(targets[name]), self.floor), CEILING)
            wanted[name] = target
            current = ((v >> off) & 0x3F) + 40
            if self.shown(current, pid) == target:
                continue                                  # already shows as this: leave the bits alone
            stored = self._stored_for(target, pid, current)
            v = (v & ~(0x3F << off)) | ((stored - 40) << off)
            changed += 1
        if not changed:
            return 0
        if (before ^ v) & ~self.mask:
            raise CompileRefused(f"pid {pid}: the ability write reached outside the ability fields")
        rec[:] = v.to_bytes(len(rec), "little")
        after = self.read(rec, pid)
        wrong = {k: (after[k], want) for k, want in wanted.items() if after[k] != want}
        if wrong:
            raise CompileRefused(f"pid {pid}: abilities do not read back as written {wrong}")
        return changed
