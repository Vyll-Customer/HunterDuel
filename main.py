"""Pure-Python balance rules for Hunter Duel.

This module deliberately has no pygame dependency.  It is used by the game,
but it can also be unit-tested on machines without a display.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


ARCHETYPE_LABELS = {
    "impact": "Enhancement",
    "projectile": "Emission",
    "mobility": "Transmutation",
    "counter": "Manipulation",
}


@dataclass(frozen=True)
class TechniqueDraft:
    name: str = "Hunter Pulse"
    archetype: str = "impact"
    power: int = 7
    reach: int = 4
    speed: int = 6
    control: int = 5
    color_index: int = 0


@dataclass(frozen=True)
class Technique:
    name: str
    archetype: str
    damage: int
    reach: int
    startup: float
    active: float
    recovery: float
    aura_cost: int
    cooldown: float
    knockback: float
    projectile_speed: float
    mobility: float
    guard_damage: int
    color_index: int
    balance_rating: int
    balance_note: str

    @property
    def total_time(self) -> float:
        return self.startup + self.active + self.recovery

    def to_dict(self) -> dict:
        return asdict(self)


class TechniqueBalancer:
    """Turns a fantasy-style draft into competitive frame data.

    Four creative sliders can be maxed, but high values create automatic
    trade-offs.  This keeps every technique in a narrow effective-power band.
    """

    VALID_ARCHETYPES = tuple(ARCHETYPE_LABELS)

    @classmethod
    def balance(cls, draft: TechniqueDraft) -> Technique:
        archetype = draft.archetype if draft.archetype in cls.VALID_ARCHETYPES else "impact"
        name = (draft.name.strip() or "Unnamed Technique")[:22]
        p = clamp(draft.power, 1, 10)
        r = clamp(draft.reach, 1, 10)
        s = clamp(draft.speed, 1, 10)
        c = clamp(draft.control, 1, 10)

        # Requested strength above the fair budget becomes explicit drawbacks.
        requested = p + r + s + c
        overload = max(0.0, requested - 24.0)
        focus = max(0.0, 18.0 - requested)

        damage = 12 + p * 2.1
        reach = 68 + r * 18
        startup = 0.34 - s * 0.019
        recovery = 0.38 - c * 0.014
        active = 0.10 + r * 0.006
        aura_cost = 10 + int((p * 1.2 + r * 0.65 + s * 0.55) * 0.75)
        cooldown = 1.25 + p * 0.05 + r * 0.035 - c * 0.045
        knockback = 300 + p * 32
        projectile_speed = 600 + s * 42
        mobility = 100 + s * 16
        guard_damage = 5 + int(p * 0.75)

        if archetype == "impact":
            damage *= 1.16
            reach *= 0.78
            startup += 0.035
            knockback *= 1.18
            note = "heavy finisher with short reach"
        elif archetype == "projectile":
            damage *= 0.86
            reach *= 1.55
            recovery += 0.045
            aura_cost += 2
            note = "range control with lower contact damage"
        elif archetype == "mobility":
            damage *= 0.90
            reach *= 0.92
            startup -= 0.035
            recovery -= 0.025
            mobility *= 1.65
            note = "fast approach with lower burst"
        else:  # counter
            damage *= 1.02
            reach *= 0.88
            startup += 0.05
            active += 0.10
            recovery += 0.035
            guard_damage += 3
            note = "counter window that punishes aggression"

        # AI-applied overload compensation.
        damage *= 1.0 - overload * 0.012
        startup += overload * 0.010
        recovery += overload * 0.012
        aura_cost += int(round(overload * 0.85))
        cooldown += overload * 0.065

        # Under-budget builds receive a small usability floor.
        startup -= min(focus * 0.004, 0.025)
        aura_cost -= min(int(focus // 3), 2)

        damage_i = int(round(clamp(damage, 15, 38)))
        reach_i = int(round(clamp(reach, 76, 330)))
        startup = round(clamp(startup, 0.11, 0.50), 3)
        active = round(clamp(active, 0.08, 0.25), 3)
        recovery = round(clamp(recovery, 0.17, 0.58), 3)
        aura_cost = int(clamp(aura_cost, 10, 36))
        cooldown = round(clamp(cooldown, 0.9, 2.8), 2)

        # A readable 0-100 grade based on proximity to the target power band.
        score = (
            damage_i * 1.55
            + reach_i * 0.07
            + (0.55 - startup) * 48
            + (0.65 - recovery) * 24
            - aura_cost * 0.58
            - cooldown * 3.5
        )
        rating = int(round(clamp(100 - abs(score - 67) * 1.7, 72, 100)))
        if overload:
            balance_note = f"AI: {note}; excess power is offset by aura cost and recovery."
        else:
            balance_note = f"AI: {note}; parameters fit the competitive power budget."

        return Technique(
            name=name,
            archetype=archetype,
            damage=damage_i,
            reach=reach_i,
            startup=startup,
            active=active,
            recovery=recovery,
            aura_cost=aura_cost,
            cooldown=cooldown,
            knockback=round(knockback, 1),
            projectile_speed=round(projectile_speed, 1),
            mobility=round(mobility, 1),
            guard_damage=guard_damage,
            color_index=int(clamp(draft.color_index, 0, 4)),
            balance_rating=rating,
            balance_note=balance_note,
        )


@dataclass(frozen=True)
class AttackSpec:
    name: str
    damage: int
    startup: float
    active: float
    recovery: float
    reach: int
    knockback: float
    aura_gain: int
    hitstun: float

    @property
    def total_time(self) -> float:
        return self.startup + self.active + self.recovery


LIGHT_ATTACK = AttackSpec("Quick", 7, 0.08, 0.08, 0.16, 78, 195, 8, 0.15)
HEAVY_ATTACK = AttackSpec("Heavy", 13, 0.18, 0.10, 0.30, 104, 360, 13, 0.24)


def special_attack(technique: Technique) -> AttackSpec:
    return AttackSpec(
        technique.name,
        technique.damage,
        technique.startup,
        technique.active,
        technique.recovery,
        technique.reach,
        technique.knockback,
        0,
        clamp(0.24 + technique.damage * 0.006, 0.28, 0.46),
    )


def save_draft(path: str | Path, draft: TechniqueDraft) -> None:
    Path(path).write_text(json.dumps(asdict(draft), ensure_ascii=False, indent=2), encoding="utf-8")


def load_draft(path: str | Path) -> TechniqueDraft:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return TechniqueDraft(**data)
