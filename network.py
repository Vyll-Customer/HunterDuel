"""HUNTER DUEL: Nen Protocol — a clean procedural 2D fighting prototype."""

from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass

try:
    import pygame
except ImportError:
    print("Brakuje Pygame. Uruchom: python -m pip install -r requirements.txt")
    raise SystemExit(1)

from game_core import (
    ARCHETYPE_LABELS,
    HEAVY_ATTACK,
    LIGHT_ATTACK,
    AttackSpec,
    Technique,
    TechniqueBalancer,
    TechniqueDraft,
    load_draft,
    save_draft,
    special_attack,
)
from app_paths import bundled_path, mods_dir, user_data_dir
from content_loader import load_mod_drafts
from network import DEFAULT_PORT, PROTOCOL_VERSION, NetworkPeer, local_ip


WIDTH, HEIGHT = 1280, 720
FPS = 60
GROUND_Y = 596
CONFIG_PATH = user_data_dir() / "last_technique.json"

INK = (229, 237, 244)
MUTED = (126, 143, 158)
DARK = (8, 13, 21)
PANEL = (16, 25, 37)
PANEL_2 = (23, 35, 49)
LINE = (42, 59, 75)
RED = (255, 86, 104)
GREEN = (93, 225, 166)
GOLD = (255, 202, 89)
AURA_COLORS = [
    (53, 225, 255),
    (255, 85, 166),
    (255, 197, 72),
    (139, 105, 255),
    (83, 235, 142),
]


def clamp(value, low, high):
    return max(low, min(high, value))


def lerp(a, b, t):
    return a + (b - a) * t


def ease_out(t):
    return 1 - (1 - clamp(t, 0, 1)) ** 3


def lighten(color, amount=0.2):
    return tuple(int(lerp(c, 255, amount)) for c in color)


def darken(color, amount=0.2):
    return tuple(int(c * (1 - amount)) for c in color)


def draw_text(surface, font, text, color, pos, anchor="topleft"):
    image = font.render(str(text), True, color)
    rect = image.get_rect()
    setattr(rect, anchor, pos)
    surface.blit(image, rect)
    return rect


def draw_round_rect(surface, rect, color, radius=12, width=0, border_color=None):
    pygame.draw.rect(surface, color, rect, width=width, border_radius=radius)
    if border_color is not None:
        pygame.draw.rect(surface, border_color, rect, width=1, border_radius=radius)


def make_background():
    surface = pygame.Surface((WIDTH, HEIGHT))
    top = (8, 15, 26)
    bottom = (20, 36, 48)
    for y in range(HEIGHT):
        t = y / HEIGHT
        pygame.draw.line(surface, tuple(int(lerp(a, b, t)) for a, b in zip(top, bottom)), (0, y), (WIDTH, y))

    # Moon and skyline are intentionally geometric and low-noise.
    glow = pygame.Surface((280, 280), pygame.SRCALPHA)
    for r in range(135, 25, -8):
        alpha = int(2 + (135 - r) * 0.035)
        pygame.draw.circle(glow, (72, 196, 220, alpha), (140, 140), r)
    pygame.draw.circle(glow, (177, 229, 230, 34), (140, 140), 50)
    surface.blit(glow, (820, 40))

    # Layered wilderness and exam-ruin silhouettes give the arena an
    # adventurous anime-hunter identity without using franchise assets.
    far_mountains = [(0, 430), (145, 285), (275, 412), (430, 248), (610, 420),
                     (795, 272), (930, 414), (1090, 260), (1280, 425)]
    pygame.draw.polygon(surface, (12, 29, 40), far_mountains + [(WIDTH, 520), (0, 520)])
    near_hills = [(0, 466), (110, 408), (230, 454), (355, 372), (520, 458),
                  (675, 391), (820, 462), (975, 382), (1138, 449), (1280, 397)]
    pygame.draw.polygon(surface, (11, 23, 32), near_hills + [(WIDTH, 560), (0, 560)])
    for x in range(-20, WIDTH + 40, 58):
        base = 485 - ((x * 7) % 24)
        height = 42 + ((x * 11) % 35)
        pygame.draw.rect(surface, (9, 21, 28), (x + 17, base - height // 3, 7, height), border_radius=3)
        pygame.draw.polygon(surface, (10, 31, 36), [(x - 5, base - 15), (x + 21, base - height), (x + 47, base - 15)])
    # Broken stone pillars suggest an old hunter trial arena.
    for x, top_y, width in ((74, 389, 28), (1160, 365, 34)):
        pygame.draw.rect(surface, (21, 41, 48), (x, top_y, width, 132))
        pygame.draw.polygon(surface, (28, 52, 58), [(x - 8, top_y + 3), (x + width // 2, top_y - 12), (x + width + 5, top_y + 8)])

    pygame.draw.rect(surface, (18, 31, 41), (0, GROUND_Y, WIDTH, HEIGHT - GROUND_Y))
    pygame.draw.line(surface, (54, 102, 111), (0, GROUND_Y), (WIDTH, GROUND_Y), 2)
    for x in range(-120, WIDTH + 120, 120):
        pygame.draw.line(surface, (23, 44, 54), (WIDTH // 2, GROUND_Y), (x, HEIGHT), 1)
    for y in (626, 662, 700):
        pygame.draw.line(surface, (23, 44, 54), (0, y), (WIDTH, y), 1)
    return surface


@dataclass
class Intent:
    left: bool = False
    right: bool = False
    jump: bool = False
    block: bool = False
    dash: bool = False
    light: bool = False
    heavy: bool = False
    special: bool = False


def intent_payload(intent):
    return {key: bool(getattr(intent, key)) for key in Intent.__dataclass_fields__}


def intent_from_payload(payload):
    if not isinstance(payload, dict):
        return Intent()
    return Intent(**{key: bool(payload.get(key, False)) for key in Intent.__dataclass_fields__})


def safe_draft(payload):
    if not isinstance(payload, dict):
        return TechniqueDraft()
    archetype = payload.get("archetype", "impact")
    if archetype not in TechniqueBalancer.VALID_ARCHETYPES:
        archetype = "impact"
    def number(name, default, low=1, high=10):
        try:
            return max(low, min(high, int(payload.get(name, default))))
        except (TypeError, ValueError):
            return default
    return TechniqueDraft(
        name=str(payload.get("name", "Online Technique"))[:22],
        archetype=archetype,
        power=number("power", 5), reach=number("reach", 5),
        speed=number("speed", 5), control=number("control", 5),
        color_index=number("color_index", 0, 0, 4),
    )


class Particle:
    def __init__(self, x, y, color, speed=280, life=0.45, size=5):
        angle = random.uniform(0, math.tau)
        force = random.uniform(speed * 0.35, speed)
        self.x, self.y = x, y
        self.vx, self.vy = math.cos(angle) * force, math.sin(angle) * force
        self.color = color
        self.life = self.max_life = life * random.uniform(0.7, 1.15)
        self.size = size * random.uniform(0.6, 1.4)

    def update(self, dt):
        self.life -= dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.vx *= 0.91 ** (dt * 60)
        self.vy = self.vy * (0.94 ** (dt * 60)) + 240 * dt

    def draw(self, surface, offset):
        if self.life <= 0:
            return
        t = self.life / self.max_life
        radius = max(1, int(self.size * t))
        pygame.draw.circle(surface, self.color, (int(self.x + offset[0]), int(self.y + offset[1])), radius)


class AfterImage:
    def __init__(self, x, y, facing, color):
        self.x, self.y, self.facing = x, y, facing
        self.color = color
        self.life = 0.18

    def update(self, dt):
        self.life -= dt

    def draw(self, surface, offset):
        alpha = int(70 * clamp(self.life / 0.18, 0, 1))
        ghost = pygame.Surface((100, 170), pygame.SRCALPHA)
        pygame.draw.circle(ghost, (*self.color, alpha), (50, 25), 18)
        pygame.draw.polygon(ghost, (*self.color, alpha), [(35, 46), (66, 46), (72, 112), (28, 112)])
        surface.blit(ghost, (self.x - 50 + offset[0], self.y - 146 + offset[1]))


class Projectile:
    def __init__(self, owner, technique):
        self.owner = owner
        self.technique = technique
        self.facing = owner.facing
        self.x = owner.x + owner.facing * 62
        self.y = owner.y - 86
        self.vx = owner.facing * technique.projectile_speed
        self.life = 1.0
        self.radius = 18 + technique.damage // 5
        self.hit = False

    @property
    def rect(self):
        return pygame.Rect(int(self.x - self.radius), int(self.y - self.radius), self.radius * 2, self.radius * 2)

    def update(self, dt):
        self.x += self.vx * dt
        self.life -= dt

    def draw(self, surface, offset):
        color = AURA_COLORS[self.technique.color_index]
        fx = pygame.Surface((self.radius * 5, self.radius * 5), pygame.SRCALPHA)
        center = fx.get_width() // 2
        pygame.draw.circle(fx, (*color, 25), (center, center), self.radius * 2)
        pygame.draw.circle(fx, (*color, 70), (center, center), int(self.radius * 1.45))
        pygame.draw.circle(fx, (*lighten(color, 0.55), 245), (center, center), self.radius)
        tail_x = center - self.facing * self.radius * 2
        pygame.draw.line(fx, (*color, 110), (center, center), (tail_x, center), self.radius)
        surface.blit(fx, (self.x - center + offset[0], self.y - center + offset[1]))


class Fighter:
    WIDTH = 58
    HEIGHT = 140

    def __init__(self, x, color, accent, name, technique):
        self.x = float(x)
        self.y = float(GROUND_Y)
        self.vx = self.vy = 0.0
        self.color = color
        self.accent = accent
        self.skin = (225, 177, 142) if "01" in name or "HOST" in name else (183, 126, 112)
        self.hair = (20, 30, 39) if "01" in name or "HOST" in name else (48, 20, 42)
        self.outline = (5, 10, 16)
        self.name = name
        self.technique = technique
        self.facing = 1
        self.health = 100.0
        self.aura = 55.0
        self.state = "idle"
        self.state_t = 0.0
        self.attack: AttackSpec | None = None
        self.attack_kind = ""
        self.attack_connected = False
        self.special_spawned = False
        self.special_cooldown = 0.0
        self.hitstun = 0.0
        self.dash_cooldown = 0.0
        self.invuln = 0.0
        self.on_ground = True
        self.combo = 0
        self.combo_timer = 0.0
        self.last_hit_damage = 0
        self.afterimage_clock = 0.0

    @property
    def rect(self):
        return pygame.Rect(int(self.x - self.WIDTH / 2), int(self.y - self.HEIGHT), self.WIDTH, self.HEIGHT)

    @property
    def locked(self):
        return self.state in ("attack", "hit", "dash", "ko")

    @property
    def attacking_active(self):
        if self.state != "attack" or self.attack is None:
            return False
        return self.attack.startup <= self.state_t < self.attack.startup + self.attack.active

    def start_attack(self, kind):
        if self.locked or not self.on_ground:
            return False
        if kind == "light":
            attack = LIGHT_ATTACK
        elif kind == "heavy":
            attack = HEAVY_ATTACK
        else:
            if self.aura < self.technique.aura_cost or self.special_cooldown > 0:
                return False
            attack = special_attack(self.technique)
            self.aura -= self.technique.aura_cost
            self.special_cooldown = self.technique.cooldown
        self.attack = attack
        self.attack_kind = kind
        self.state = "attack"
        self.state_t = 0.0
        self.attack_connected = False
        self.special_spawned = False
        self.vx *= 0.18
        return True

    def take_hit(self, damage, knockback, hitstun, direction, blocked=False):
        if self.invuln > 0 or self.state == "ko":
            return 0
        if blocked:
            aura_damage = damage * 1.25
            self.aura = max(0.0, self.aura - aura_damage)
            actual = max(1, int(damage * 0.18))
            self.health = max(0.0, self.health - actual)
            self.vx = direction * knockback * 0.18
            if self.aura <= 0:
                self.state = "hit"
                self.hitstun = 0.42
            return actual
        actual = int(damage)
        self.health = max(0.0, self.health - actual)
        self.vx = direction * knockback
        self.vy = -min(260, knockback * 0.38)
        self.state = "ko" if self.health <= 0 else "hit"
        self.state_t = 0.0
        self.hitstun = hitstun
        self.attack = None
        return actual

    def attack_box(self):
        if not self.attacking_active or self.attack is None:
            return pygame.Rect(0, 0, 0, 0)
        reach = self.attack.reach
        if self.attack_kind == "special" and self.technique.archetype == "projectile":
            return pygame.Rect(0, 0, 0, 0)
        if self.facing > 0:
            return pygame.Rect(int(self.x + 12), int(self.y - 119), reach, 88)
        return pygame.Rect(int(self.x - 12 - reach), int(self.y - 119), reach, 88)

    def update(self, dt, intent, other, afterimages):
        self.state_t += dt
        self.special_cooldown = max(0.0, self.special_cooldown - dt)
        self.dash_cooldown = max(0.0, self.dash_cooldown - dt)
        self.invuln = max(0.0, self.invuln - dt)
        self.combo_timer = max(0.0, self.combo_timer - dt)
        if self.combo_timer <= 0:
            self.combo = 0
        if self.health <= 0:
            self.state = "ko"

        if self.state == "ko":
            self.vx *= 0.92 ** (dt * 60)
        elif self.state == "hit":
            self.hitstun -= dt
            if self.hitstun <= 0:
                self.state, self.state_t = "idle", 0.0
        elif self.state == "attack":
            if self.attack and self.state_t >= self.attack.startup + self.attack.active + self.attack.recovery:
                self.state, self.state_t, self.attack = "idle", 0.0, None
        elif self.state == "dash":
            self.afterimage_clock -= dt
            if self.afterimage_clock <= 0:
                afterimages.append(AfterImage(self.x, self.y, self.facing, self.accent))
                self.afterimage_clock = 0.04
            if self.state_t >= 0.16:
                self.state, self.state_t = "idle", 0.0
                self.vx *= 0.28
        else:
            if intent.dash and self.dash_cooldown <= 0:
                direction = -1 if intent.left else 1 if intent.right else self.facing
                self.state, self.state_t = "dash", 0.0
                self.vx = direction * 710
                self.invuln = 0.07
                self.dash_cooldown = 0.65
                self.afterimage_clock = 0
            elif intent.light:
                self.start_attack("light")
            elif intent.heavy:
                self.start_attack("heavy")
            elif intent.special:
                self.start_attack("special")
            else:
                move = int(intent.right) - int(intent.left)
                if intent.block and self.on_ground:
                    self.state = "block"
                    self.vx *= 0.72 ** (dt * 60)
                else:
                    self.state = "run" if move else "idle"
                    target = move * 310
                    self.vx = lerp(self.vx, target, min(1, dt * 14))
                if intent.jump and self.on_ground and not intent.block:
                    self.vy = -570
                    self.on_ground = False
                    self.state = "jump"

        if self.state not in ("attack", "hit", "dash", "ko") and abs(other.x - self.x) > 8:
            self.facing = 1 if other.x > self.x else -1

        if not self.on_ground:
            self.vy += 1450 * dt
            if self.state not in ("hit", "ko"):
                self.state = "jump"
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.x = clamp(self.x, 42, WIDTH - 42)
        if self.y >= GROUND_Y:
            self.y = GROUND_Y
            self.vy = 0
            self.on_ground = True
            if self.state == "jump":
                self.state, self.state_t = "idle", 0.0
        else:
            self.on_ground = False

        # Passive aura rewards neutral play without allowing endless specials.
        self.aura = min(100.0, self.aura + dt * (2.2 if self.state != "block" else 0.6))

    def draw(self, surface, offset=(0, 0)):
        ox, oy = offset
        x, floor = self.x + ox, self.y + oy
        t = self.state_t
        aura_color = AURA_COLORS[self.technique.color_index]

        # Shadow.
        shadow_w = 56 if self.on_ground else 40
        pygame.draw.ellipse(surface, (3, 8, 12), (x - shadow_w, GROUND_Y - 8 + oy, shadow_w * 2, 16))

        # Aura breathes and spikes during specials.
        aura_strength = 0.14 + self.aura / 100 * 0.12
        if self.attack_kind == "special" and self.state == "attack":
            aura_strength += 0.38
        aura = pygame.Surface((150, 190), pygame.SRCALPHA)
        pulse = 4 * math.sin(pygame.time.get_ticks() * 0.006)
        pygame.draw.ellipse(aura, (*aura_color, int(55 * aura_strength)), (24 - pulse, 16, 102 + pulse * 2, 160))
        for i in range(3):
            ay = 150 - ((pygame.time.get_ticks() * (0.04 + i * 0.008) + i * 41) % 130)
            pygame.draw.circle(aura, (*aura_color, 65), (42 + i * 32, int(ay)), 2 + i)
        surface.blit(aura, (x - 75, floor - 170))

        # Pose values.
        bob = 0 if self.state in ("hit", "ko") else math.sin(t * 9) * (3 if self.state == "run" else 1.4)
        lean = 0
        arm_front = (30 * self.facing, 64)
        arm_back = (-20 * self.facing, 68)
        leg_front = (20 * self.facing, 132)
        leg_back = (-17 * self.facing, 132)
        if self.state == "run":
            phase = math.sin(t * 15)
            arm_front = (28 * phase * self.facing, 75)
            arm_back = (-28 * phase * self.facing, 73)
            leg_front = (-25 * phase * self.facing, 134)
            leg_back = (25 * phase * self.facing, 134)
            lean = 7 * self.facing
        elif self.state == "jump":
            arm_front, arm_back = (25 * self.facing, 55), (-22 * self.facing, 50)
            leg_front, leg_back = (24 * self.facing, 116), (-22 * self.facing, 112)
        elif self.state == "block":
            arm_front, arm_back = (26 * self.facing, 47), (19 * self.facing, 70)
            lean = -6 * self.facing
        elif self.state == "hit":
            lean = -15 * self.facing
            arm_front, arm_back = (-26 * self.facing, 52), (-32 * self.facing, 78)
        elif self.state == "ko":
            lean = -46 * self.facing * ease_out(min(1, t * 2.2))
            bob += min(42, t * 80)
        elif self.state == "dash":
            lean = 14 * self.facing
            arm_front, arm_back = (-27 * self.facing, 69), (-32 * self.facing, 80)
        elif self.state == "attack" and self.attack:
            total = max(0.01, self.attack.total_time)
            phase = self.state_t / total
            if self.state_t < self.attack.startup:
                wind = ease_out(self.state_t / max(0.01, self.attack.startup))
                arm_front = (-28 * wind * self.facing, 62)
                lean = -6 * wind * self.facing
            elif self.attacking_active:
                strike = (self.state_t - self.attack.startup) / max(0.01, self.attack.active)
                extension = 39 + min(62, self.attack.reach * 0.25)
                arm_front = (extension * self.facing, 58 - math.sin(strike * math.pi) * 8)
                lean = 12 * self.facing
            else:
                arm_front = (32 * (1 - phase) * self.facing, 62)

        hip = pygame.Vector2(x + lean * 0.35, floor - 58 - bob)
        shoulder = pygame.Vector2(x + lean, floor - 112 - bob)
        head = pygame.Vector2(x + lean * 1.18, floor - 139 - bob)

        def limb(start, delta, color, width=11, end_color=None):
            end = pygame.Vector2(x + delta[0], floor - (140 - delta[1]) - bob)
            mid = (start + end) * 0.5 + pygame.Vector2(self.facing * 4, 7)
            pygame.draw.line(surface, self.outline, start, mid, width + 5)
            pygame.draw.line(surface, color, start, mid, width)
            pygame.draw.line(surface, self.outline, mid, end, width + 4)
            pygame.draw.line(surface, color, mid, end, width - 1)
            pygame.draw.circle(surface, self.outline, end, width // 2 + 2)
            pygame.draw.circle(surface, end_color or lighten(color, 0.25), end, width // 2)

        boot = darken(self.color, 0.65)
        limb(hip, leg_back, darken(self.color, 0.24), 13, boot)
        limb(shoulder, arm_back, darken(self.color, 0.16), 11, self.skin)

        body_points = [
            (shoulder.x - 17, shoulder.y - 4),
            (shoulder.x + 18, shoulder.y - 4),
            (hip.x + 18, hip.y + 5),
            (hip.x - 17, hip.y + 5),
        ]
        pygame.draw.polygon(surface, self.outline, body_points)
        inner = [(px + (2 if px < x else -2), py + 2) for px, py in body_points]
        pygame.draw.polygon(surface, self.color, inner)
        # Jacket panels, collar and belt create a more grounded costume.
        pygame.draw.polygon(surface, darken(self.color, 0.16), [(shoulder.x, shoulder.y), (hip.x + 3, hip.y), (hip.x + 15, hip.y), (shoulder.x + 15, shoulder.y)])
        pygame.draw.polygon(surface, self.skin, [(shoulder.x - 8, shoulder.y - 3), (shoulder.x, shoulder.y + 11), (shoulder.x + 9, shoulder.y - 3)])
        pygame.draw.line(surface, self.accent, (shoulder.x - 13, shoulder.y + 8), (hip.x + 8, hip.y - 1), 5)
        pygame.draw.line(surface, self.outline, (hip.x - 16, hip.y - 1), (hip.x + 17, hip.y + 2), 5)
        pygame.draw.line(surface, self.accent, (hip.x - 14, hip.y - 1), (hip.x + 15, hip.y + 1), 2)

        limb(hip, leg_front, self.color, 13, boot)
        limb(shoulder, arm_front, self.color, 11, self.skin)

        pygame.draw.rect(surface, self.skin, (head.x - 6, head.y + 13, 12, 13), border_radius=4)
        pygame.draw.ellipse(surface, self.outline, (head.x - 20, head.y - 21, 40, 44))
        pygame.draw.ellipse(surface, self.skin, (head.x - 17, head.y - 18, 34, 39))
        ear_x = head.x - self.facing * 17
        pygame.draw.circle(surface, self.skin, (ear_x, head.y + 1), 5)
        # Asymmetric spiky hair reads clearly during motion and remains original.
        hair_points = [
            (head.x - 18, head.y - 4), (head.x - 20, head.y - 21),
            (head.x - 8, head.y - 16), (head.x - 3, head.y - 31),
            (head.x + 4, head.y - 18), (head.x + 15, head.y - 27),
            (head.x + 18, head.y - 7), (head.x + 9, head.y - 13),
            (head.x - 2, head.y - 10),
        ]
        pygame.draw.polygon(surface, self.outline, hair_points)
        inner_hair = [(px, py + 2) for px, py in hair_points]
        pygame.draw.polygon(surface, self.hair, inner_hair)
        eye_x = head.x + self.facing * 8
        pygame.draw.line(surface, self.outline, (eye_x - self.facing * 3, head.y - 1), (eye_x + self.facing * 5, head.y - 2), 3)
        pygame.draw.circle(surface, aura_color, (int(eye_x + self.facing * 3), int(head.y - 2)), 1)
        pygame.draw.line(surface, darken(self.skin, 0.35), (head.x + self.facing * 6, head.y + 4), (head.x + self.facing * 9, head.y + 7), 1)
        pygame.draw.line(surface, darken(self.skin, 0.45), (head.x + self.facing * 2, head.y + 13), (head.x + self.facing * 9, head.y + 12), 2)

        if self.state == "block":
            shield = pygame.Surface((88, 132), pygame.SRCALPHA)
            side = 0 if self.facing > 0 else 18
            pygame.draw.arc(shield, (*aura_color, 155), (side, 4, 68, 122), -1.2, 1.2, 5)
            surface.blit(shield, (x + self.facing * 18 - (0 if self.facing > 0 else 88), floor - 139))

        if self.attacking_active and self.attack_kind == "special" and self.technique.archetype != "projectile":
            box = self.attack_box().move(ox, oy)
            slash = pygame.Surface((box.width + 70, box.height + 70), pygame.SRCALPHA)
            if self.technique.archetype == "impact":
                pygame.draw.circle(slash, (*aura_color, 55), (slash.get_width() // 2, slash.get_height() // 2), min(box.width, 68))
                pygame.draw.circle(slash, (*aura_color, 180), (slash.get_width() // 2, slash.get_height() // 2), min(box.width, 52), 5)
            else:
                pygame.draw.arc(slash, (*aura_color, 190), (8, 7, slash.get_width() - 16, slash.get_height() - 14), -1.0, 1.0, 8)
            surface.blit(slash, (box.x - 35, box.y - 35))


class DuelAI:
    def __init__(self):
        self.think_timer = 0
        self.plan = Intent()
        self.aggression = random.uniform(0.82, 1.05)

    def think(self, me, enemy, dt):
        self.think_timer -= dt
        if self.think_timer > 0:
            # Holding movement/block is useful; attacks are one-frame decisions.
            result = self.plan
            self.plan = Intent(left=result.left, right=result.right, block=result.block)
            return result
        self.think_timer = random.uniform(0.075, 0.14)
        distance = abs(enemy.x - me.x)
        direction_right = enemy.x > me.x
        intent = Intent()

        if enemy.attacking_active and distance < (enemy.attack.reach + 55 if enemy.attack else 130):
            if random.random() < 0.72:
                intent.block = True
            elif me.dash_cooldown <= 0:
                intent.left = direction_right
                intent.right = not direction_right
                intent.dash = True
            self.plan = intent
            return intent

        ideal = 165 if me.technique.archetype == "projectile" else 88
        if distance > ideal + 45:
            intent.right = direction_right
            intent.left = not direction_right
            if distance > 310 and me.dash_cooldown <= 0 and random.random() < 0.14:
                intent.dash = True
        elif distance < ideal - 45:
            intent.left = direction_right
            intent.right = not direction_right

        if not me.locked:
            special_range = me.technique.reach + (100 if me.technique.archetype == "projectile" else 20)
            if me.aura >= me.technique.aura_cost and me.special_cooldown <= 0 and distance < special_range:
                if random.random() < 0.22 * self.aggression:
                    intent.special = True
            elif distance < 116 and random.random() < 0.34 * self.aggression:
                intent.light = random.random() < 0.68
                intent.heavy = not intent.light
        self.plan = intent
        return intent


class FightScene:
    def __init__(self, app, technique, versus_ai=True):
        self.app = app
        self.technique = technique
        rival_draft = TechniqueDraft(
            name="Mirror Bind",
            archetype=random.choice(["impact", "mobility", "counter"]),
            power=random.randint(4, 8), reach=random.randint(3, 8),
            speed=random.randint(4, 8), control=random.randint(4, 8), color_index=3,
        )
        rival_tech = TechniqueBalancer.balance(rival_draft)
        self.p1 = Fighter(330, (36, 94, 132), AURA_COLORS[technique.color_index], "HUNTER 01", technique)
        self.p2 = Fighter(950, (118, 48, 79), AURA_COLORS[rival_tech.color_index], "HUNTER 02" if not versus_ai else "ECHO AI", rival_tech)
        self.p2.facing = -1
        self.versus_ai = versus_ai
        self.ai = DuelAI()
        self.just_pressed = set()
        self.projectiles = []
        self.particles = []
        self.afterimages = []
        self.hitstop = 0
        self.shake = 0
        self.round_time = 60.0
        self.intro = 2.45
        self.finished = False
        self.finish_timer = 0
        self.paused = False
        self.background = make_background()

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.paused = not self.paused
            elif event.key == pygame.K_r and self.finished:
                self.app.scene = FightScene(self.app, self.technique, self.versus_ai)
            else:
                self.just_pressed.add(event.key)

    def player_intent(self, player):
        keys = pygame.key.get_pressed()
        if player == 1:
            return Intent(
                left=keys[pygame.K_a], right=keys[pygame.K_d], jump=pygame.K_w in self.just_pressed,
                block=keys[pygame.K_f], dash=pygame.K_q in self.just_pressed,
                light=pygame.K_g in self.just_pressed, heavy=pygame.K_h in self.just_pressed,
                special=pygame.K_j in self.just_pressed,
            )
        return Intent(
            left=keys[pygame.K_LEFT], right=keys[pygame.K_RIGHT], jump=pygame.K_UP in self.just_pressed,
            block=keys[pygame.K_RCTRL], dash=pygame.K_RSHIFT in self.just_pressed,
            light=pygame.K_KP1 in self.just_pressed, heavy=pygame.K_KP2 in self.just_pressed,
            special=pygame.K_KP3 in self.just_pressed,
        )

    def resolve_body_collision(self):
        if not self.p1.rect.colliderect(self.p2.rect):
            return
        overlap = min(self.p1.rect.right, self.p2.rect.right) - max(self.p1.rect.left, self.p2.rect.left)
        if overlap <= 0:
            return
        push = overlap * 0.5 + 0.5
        if self.p1.x < self.p2.x:
            self.p1.x -= push
            self.p2.x += push
        else:
            self.p1.x += push
            self.p2.x -= push
        self.p1.x = clamp(self.p1.x, 42, WIDTH - 42)
        self.p2.x = clamp(self.p2.x, 42, WIDTH - 42)

    def spawn_hit_fx(self, x, y, color, strong=False, blocked=False):
        count = 7 if blocked else (22 if strong else 13)
        fx_color = MUTED if blocked else color
        for _ in range(count):
            self.particles.append(Particle(x, y, fx_color, 390 if strong else 260, 0.5, 6 if strong else 4))
        self.shake = max(self.shake, 9 if strong else 4)
        self.hitstop = max(self.hitstop, 0.085 if strong else 0.045)

    def apply_attack(self, attacker, defender):
        if not attacker.attacking_active or attacker.attack_connected or attacker.attack is None:
            return
        if attacker.attack_kind == "special" and attacker.technique.archetype == "projectile":
            if not attacker.special_spawned:
                self.projectiles.append(Projectile(attacker, attacker.technique))
                attacker.special_spawned = True
                attacker.attack_connected = True
            return
        hitbox = attacker.attack_box()
        if not hitbox.colliderect(defender.rect):
            return
        blocked = defender.state == "block" and defender.facing == -attacker.facing
        damage = attacker.attack.damage
        hitstun = attacker.attack.hitstun
        knockback = attacker.attack.knockback
        # Each extra hit pushes farther and stuns for less time. Long loops
        # naturally break apart instead of becoming unavoidable touch-of-death combos.
        combo_scaling = min(attacker.combo, 5)
        knockback *= 1.0 + combo_scaling * 0.18
        hitstun *= 0.90 ** combo_scaling
        if attacker.attack_kind == "special" and attacker.technique.archetype == "counter" and defender.state == "attack":
            damage = int(damage * 1.28)
            knockback *= 1.25
        actual = defender.take_hit(damage, knockback, hitstun, attacker.facing, blocked)
        attacker.attack_connected = True
        attacker.aura = min(100, attacker.aura + attacker.attack.aura_gain)
        if not blocked:
            attacker.combo = attacker.combo + 1 if attacker.combo_timer > 0 else 1
            attacker.combo_timer = 0.9
            attacker.last_hit_damage = actual
        center = defender.rect.center
        self.spawn_hit_fx(center[0], center[1] - 20, AURA_COLORS[attacker.technique.color_index], attacker.attack_kind != "light", blocked)

    def update_projectiles(self, dt):
        for projectile in self.projectiles:
            projectile.update(dt)
            defender = self.p2 if projectile.owner is self.p1 else self.p1
            if not projectile.hit and projectile.rect.colliderect(defender.rect):
                blocked = defender.state == "block" and defender.facing == -projectile.facing
                tech = projectile.technique
                actual = defender.take_hit(tech.damage, tech.knockback, 0.34, projectile.facing, blocked)
                projectile.hit = True
                projectile.life = 0
                owner = projectile.owner
                if not blocked:
                    owner.combo = owner.combo + 1 if owner.combo_timer > 0 else 1
                    owner.combo_timer = 0.9
                    owner.last_hit_damage = actual
                self.spawn_hit_fx(projectile.x, projectile.y, AURA_COLORS[tech.color_index], True, blocked)
        self.projectiles = [p for p in self.projectiles if p.life > 0 and -100 < p.x < WIDTH + 100]

    def simulate_round(self, dt, p1_intent, p2_intent):
        self.p1.update(dt, p1_intent, self.p2, self.afterimages)
        self.p2.update(dt, p2_intent, self.p1, self.afterimages)
        self.resolve_body_collision()
        self.apply_attack(self.p1, self.p2)
        self.apply_attack(self.p2, self.p1)
        self.update_projectiles(dt)

    def update_effects(self, dt):
        for p in self.particles:
            p.update(dt)
        for a in self.afterimages:
            a.update(dt)
        self.particles = [p for p in self.particles if p.life > 0]
        self.afterimages = [a for a in self.afterimages if a.life > 0]
        self.shake *= 0.83 ** (dt * 60)

    def update(self, dt):
        if self.paused:
            self.just_pressed.clear()
            return
        if self.hitstop > 0:
            self.hitstop -= dt
            self.just_pressed.clear()
            return
        if self.intro > 0:
            self.intro -= dt
            self.just_pressed.clear()
            return
        if not self.finished:
            self.round_time = max(0, self.round_time - dt)
            p1_intent = self.player_intent(1)
            p2_intent = self.ai.think(self.p2, self.p1, dt) if self.versus_ai else self.player_intent(2)
            self.simulate_round(dt, p1_intent, p2_intent)
            if self.p1.health <= 0 or self.p2.health <= 0 or self.round_time <= 0:
                self.finished = True
                self.finish_timer = 0
        else:
            self.finish_timer += dt

        self.update_effects(dt)
        self.just_pressed.clear()

    def draw_bar(self, surface, rect, value, color, reverse=False):
        draw_round_rect(surface, rect, (9, 15, 22), 7)
        inner = rect.inflate(-6, -6)
        width = int(inner.width * clamp(value / 100, 0, 1))
        fill = pygame.Rect(inner.right - width if reverse else inner.x, inner.y, width, inner.height)
        if width:
            draw_round_rect(surface, fill, color, 5)
            shine = pygame.Rect(fill.x, fill.y, fill.width, max(2, fill.height // 3))
            draw_round_rect(surface, shine, lighten(color, 0.22), 4)

    def draw_hud(self, surface):
        # Top plates.
        draw_text(surface, self.app.fonts[16], self.p1.name, INK, (54, 30))
        draw_text(surface, self.app.fonts[16], self.p2.name, INK, (WIDTH - 54, 30), "topright")
        self.draw_bar(surface, pygame.Rect(52, 52, 470, 28), self.p1.health, (55, 215, 169))
        self.draw_bar(surface, pygame.Rect(WIDTH - 522, 52, 470, 28), self.p2.health, (232, 77, 108), True)
        self.draw_bar(surface, pygame.Rect(52, 86, 320, 13), self.p1.aura, AURA_COLORS[self.p1.technique.color_index])
        self.draw_bar(surface, pygame.Rect(WIDTH - 372, 86, 320, 13), self.p2.aura, AURA_COLORS[self.p2.technique.color_index], True)
        draw_text(surface, self.app.fonts[11], f"H  {self.p1.technique.name.upper()}", MUTED, (52, 106))
        draw_text(surface, self.app.fonts[11], f"{self.p2.technique.name.upper()}  {'L' if not self.versus_ai else 'AI'}", MUTED, (WIDTH - 52, 106), "topright")

        draw_round_rect(surface, pygame.Rect(WIDTH // 2 - 43, 35, 86, 66), PANEL, 18, border_color=LINE)
        draw_text(surface, self.app.fonts[30], f"{math.ceil(self.round_time):02}", INK, (WIDTH // 2, 48), "midtop")
        draw_text(surface, self.app.fonts[10], "ROUND 01", MUTED, (WIDTH // 2, 81), "midtop")

        for fighter, right in ((self.p1, False), (self.p2, True)):
            if fighter.combo > 1 and fighter.combo_timer > 0:
                pos = (90 if not right else WIDTH - 90, 188)
                anchor = "midleft" if not right else "midright"
                draw_text(surface, self.app.fonts[36], str(fighter.combo), GOLD, pos, anchor)
                label_pos = (pos[0] + (42 if not right else -42), pos[1] + 4)
                draw_text(surface, self.app.fonts[12], "HIT COMBO", INK, label_pos, anchor)

        # Small cooldown chip.
        if self.p1.special_cooldown > 0:
            draw_round_rect(surface, pygame.Rect(52, 128, 142, 23), (31, 38, 48), 7)
            draw_text(surface, self.app.fonts[10], f"COOLDOWN {self.p1.special_cooldown:.1f}s", MUTED, (123, 134), "midtop")

    def draw(self, surface):
        shake_offset = (random.randint(-int(self.shake), int(self.shake)), random.randint(-int(self.shake), int(self.shake))) if self.shake >= 1 else (0, 0)
        surface.blit(self.background, shake_offset)
        for afterimage in self.afterimages:
            afterimage.draw(surface, shake_offset)
        self.p1.draw(surface, shake_offset)
        self.p2.draw(surface, shake_offset)
        for projectile in self.projectiles:
            projectile.draw(surface, shake_offset)
        for particle in self.particles:
            particle.draw(surface, shake_offset)
        self.draw_hud(surface)

        if self.intro > 0:
            if self.intro > 1.35:
                title, color = "ROUND 01", INK
            else:
                title, color = "FIGHT!", AURA_COLORS[self.technique.color_index]
            alpha_t = min(1, (2.45 - self.intro) * 4, self.intro * 3)
            image = self.app.fonts[64].render(title, True, color)
            image.set_alpha(int(255 * clamp(alpha_t, 0, 1)))
            surface.blit(image, image.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 55)))

        if self.finished:
            overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            overlay.fill((4, 8, 14, 150))
            surface.blit(overlay, (0, 0))
            if self.p1.health == self.p2.health:
                winner = "REMIS"
            else:
                winner = self.p1.name if self.p1.health > self.p2.health else self.p2.name
            draw_text(surface, self.app.fonts[16], "ROUND OVER", GOLD, (WIDTH // 2, 255), "midtop")
            draw_text(surface, self.app.fonts[48], winner, INK, (WIDTH // 2, 286), "midtop")
            draw_text(surface, self.app.fonts[14], "R — REMATCH     ESC — PAUSE / MENU", MUTED, (WIDTH // 2, 358), "midtop")

        if self.paused:
            overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            overlay.fill((4, 8, 14, 210))
            surface.blit(overlay, (0, 0))
            draw_text(surface, self.app.fonts[44], "PAUSED", INK, (WIDTH // 2, 230), "midtop")
            draw_text(surface, self.app.fonts[14], "ESC — RETURN TO FIGHT", MUTED, (WIDTH // 2, 300), "midtop")
            button = pygame.Rect(WIDTH // 2 - 110, 350, 220, 48)
            mouse = pygame.mouse.get_pos()
            draw_round_rect(surface, button, PANEL_2 if button.collidepoint(mouse) else PANEL, 12, border_color=LINE)
            draw_text(surface, self.app.fonts[14], "MAIN MENU", INK, button.center, "center")
            if pygame.mouse.get_pressed()[0] and button.collidepoint(mouse):
                self.app.scene = MenuScene(self.app)


class OnlineFightScene(FightScene):
    """Host-authoritative online duel for exactly two players."""

    def __init__(self, app, host_technique, client_technique, peer, is_host):
        super().__init__(app, host_technique, versus_ai=False)
        self.peer = peer
        self.is_host = is_host
        self.p1 = Fighter(330, (36, 94, 132), AURA_COLORS[host_technique.color_index], "HOST HUNTER", host_technique)
        self.p2 = Fighter(950, (118, 48, 79), AURA_COLORS[client_technique.color_index], "GUEST HUNTER", client_technique)
        self.p2.facing = -1
        self.remote_intent = Intent()
        self.net_clock = 0.0
        self.connection_message = ""

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.peer.close()
            self.app.scene = MenuScene(self.app)
        elif event.type == pygame.KEYDOWN:
            self.just_pressed.add(event.key)

    @staticmethod
    def fighter_state(fighter):
        return {
            "x": round(fighter.x, 2), "y": round(fighter.y, 2),
            "vx": round(fighter.vx, 2), "vy": round(fighter.vy, 2),
            "facing": fighter.facing, "health": round(fighter.health, 2),
            "aura": round(fighter.aura, 2), "state": fighter.state,
            "state_t": round(fighter.state_t, 3), "attack_kind": fighter.attack_kind,
            "special_cooldown": round(fighter.special_cooldown, 2),
            "hitstun": round(fighter.hitstun, 3), "on_ground": fighter.on_ground,
            "combo": fighter.combo, "combo_timer": round(fighter.combo_timer, 3),
        }

    def snapshot(self):
        return {
            "type": "state", "p1": self.fighter_state(self.p1), "p2": self.fighter_state(self.p2),
            "round_time": round(self.round_time, 2), "intro": round(self.intro, 2),
            "finished": self.finished, "finish_timer": round(self.finish_timer, 2),
            "projectiles": [
                {"owner": 1 if p.owner is self.p1 else 2, "x": round(p.x, 2), "y": round(p.y, 2),
                 "facing": p.facing, "life": round(p.life, 2)} for p in self.projectiles
            ],
        }

    @staticmethod
    def apply_fighter_state(fighter, data):
        if not isinstance(data, dict):
            return
        for key in ("x", "y", "vx", "vy", "health", "aura", "state_t", "special_cooldown", "hitstun", "combo_timer"):
            try:
                setattr(fighter, key, float(data.get(key, getattr(fighter, key))))
            except (TypeError, ValueError):
                pass
        fighter.facing = 1 if data.get("facing", fighter.facing) >= 0 else -1
        state = data.get("state", fighter.state)
        if state in ("idle", "run", "jump", "block", "dash", "attack", "hit", "ko"):
            fighter.state = state
        fighter.attack_kind = str(data.get("attack_kind", ""))
        fighter.on_ground = bool(data.get("on_ground", fighter.on_ground))
        try:
            fighter.combo = int(clamp(int(data.get("combo", fighter.combo)), 0, 99))
        except (TypeError, ValueError):
            fighter.combo = 0
        if fighter.state == "attack":
            if fighter.attack_kind == "light":
                fighter.attack = LIGHT_ATTACK
            elif fighter.attack_kind == "heavy":
                fighter.attack = HEAVY_ATTACK
            else:
                fighter.attack = special_attack(fighter.technique)
        else:
            fighter.attack = None

    def apply_snapshot(self, data):
        self.apply_fighter_state(self.p1, data.get("p1", {}))
        self.apply_fighter_state(self.p2, data.get("p2", {}))
        self.round_time = float(data.get("round_time", self.round_time))
        self.intro = float(data.get("intro", self.intro))
        self.finished = bool(data.get("finished", self.finished))
        self.finish_timer = float(data.get("finish_timer", self.finish_timer))
        synced = []
        for item in data.get("projectiles", [])[:12]:
            owner = self.p1 if item.get("owner") == 1 else self.p2
            projectile = Projectile(owner, owner.technique)
            projectile.x = float(item.get("x", projectile.x))
            projectile.y = float(item.get("y", projectile.y))
            projectile.facing = 1 if item.get("facing", 1) >= 0 else -1
            projectile.life = float(item.get("life", 0.1))
            synced.append(projectile)
        self.projectiles = synced

    def update(self, dt):
        local_intent = self.player_intent(1)
        messages = self.peer.drain()
        if self.is_host:
            for message in messages:
                if message.get("type") == "intent":
                    self.remote_intent = intent_from_payload(message.get("data"))
            if self.hitstop > 0:
                self.hitstop -= dt
            elif self.intro > 0:
                self.intro -= dt
            elif not self.finished:
                self.round_time = max(0, self.round_time - dt)
                self.simulate_round(dt, local_intent, self.remote_intent)
                if self.p1.health <= 0 or self.p2.health <= 0 or self.round_time <= 0:
                    self.finished = True
            else:
                self.finish_timer += dt
            self.net_clock -= dt
            if self.net_clock <= 0:
                self.peer.send(self.snapshot())
                self.net_clock = 1 / 30
        else:
            self.peer.send({"type": "intent", "data": intent_payload(local_intent)})
            for message in messages:
                if message.get("type") == "state":
                    self.apply_snapshot(message)

        if self.peer.error:
            self.connection_message = self.peer.error
        elif self.peer.stopped.is_set() and not self.finished:
            self.connection_message = "CONNECTION CLOSED"
        self.update_effects(dt)
        self.just_pressed.clear()

    def draw(self, surface):
        super().draw(surface)
        role = "HOST / PLAYER 1" if self.is_host else "GUEST / PLAYER 2"
        draw_round_rect(surface, pygame.Rect(WIDTH // 2 - 92, 112, 184, 24), (8, 15, 22), 8)
        draw_text(surface, self.app.fonts[9], f"ONLINE  •  {role}", GREEN, (WIDTH // 2, 119), "midtop")
        if self.connection_message:
            draw_round_rect(surface, pygame.Rect(WIDTH // 2 - 235, HEIGHT - 74, 470, 42), (55, 25, 32), 12, border_color=RED)
            draw_text(surface, self.app.fonts[12], self.connection_message[:54], INK, (WIDTH // 2, HEIGHT - 62), "midtop")


class Button:
    def __init__(self, rect, label, primary=False):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.primary = primary

    def draw(self, surface, app):
        hover = self.rect.collidepoint(pygame.mouse.get_pos())
        if self.primary:
            color = lighten(AURA_COLORS[0], 0.12) if hover else AURA_COLORS[0]
            text_color = DARK
        else:
            color = PANEL_2 if hover else PANEL
            text_color = INK
        draw_round_rect(surface, self.rect, color, 13, border_color=None if self.primary else LINE)
        draw_text(surface, app.fonts[14], self.label, text_color, self.rect.center, "center")


class MenuScene:
    def __init__(self, app):
        self.app = app
        self.bg = make_background()
        self.buttons = [
            Button((96, 365, 284, 52), "DUEL VS AI", True),
            Button((96, 427, 284, 52), "LOCAL 1V1"),
            Button((96, 489, 284, 52), "ONLINE MULTIPLAYER"),
            Button((96, 551, 284, 44), "EXIT"),
        ]

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.buttons[0].rect.collidepoint(event.pos):
                self.app.scene = CreatorScene(self.app, True)
            elif self.buttons[1].rect.collidepoint(event.pos):
                self.app.scene = CreatorScene(self.app, False)
            elif self.buttons[2].rect.collidepoint(event.pos):
                self.app.scene = OnlineMenuScene(self.app)
            elif self.buttons[3].rect.collidepoint(event.pos):
                self.app.running = False
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RETURN:
                self.app.scene = CreatorScene(self.app, True)

    def update(self, dt):
        pass

    def draw(self, surface):
        surface.blit(self.bg, (0, 0))
        shade = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        shade.fill((3, 7, 13, 74))
        surface.blit(shade, (0, 0))
        draw_text(surface, self.app.fonts[12], "ORIGINAL 2D FIGHTING PROTOTYPE", AURA_COLORS[0], (96, 90))
        draw_text(surface, self.app.fonts[68], "HUNTER", INK, (90, 118))
        draw_text(surface, self.app.fonts[68], "DUEL", AURA_COLORS[0], (90, 182))
        draw_text(surface, self.app.fonts[20], "NEN PROTOCOL", MUTED, (96, 261))
        draw_text(surface, self.app.fonts[14], "Forge a technique. AI sets the limits. You win the duel.", INK, (97, 317))
        for button in self.buttons:
            button.draw(surface, self.app)

        # Decorative fighter card on the right.
        card = pygame.Rect(660, 95, 490, 510)
        draw_round_rect(surface, card, (13, 22, 33), 28, border_color=LINE)
        draw_text(surface, self.app.fonts[11], "COMBAT SYSTEM / BUILD 1.1", MUTED, (694, 127))
        chips = [("FRAME DATA", 694), ("AI BALANCE", 805), ("60 FPS", 920)]
        for label, x in chips:
            rect = pygame.Rect(x, 164, 100, 27)
            draw_round_rect(surface, rect, PANEL_2, 8)
            draw_text(surface, self.app.fonts[9], label, INK, rect.center, "center")
        mod_chip = pygame.Rect(1035, 164, 82, 27)
        draw_round_rect(surface, mod_chip, PANEL_2, 8)
        draw_text(surface, self.app.fonts[9], f"MODY {len(self.app.mod_drafts)}", GREEN, mod_chip.center, "center")
        pygame.draw.circle(surface, (*AURA_COLORS[0],), (905, 365), 128, 2)
        pygame.draw.circle(surface, darken(AURA_COLORS[0], 0.45), (905, 365), 93, 2)
        # Use the real renderer as the hero graphic.
        preview = Fighter(905, (34, 96, 132), AURA_COLORS[0], "", TechniqueBalancer.balance(TechniqueDraft()))
        preview.y = 478
        preview.state = "attack"
        preview.attack = LIGHT_ATTACK
        preview.attack_kind = "light"
        preview.state_t = LIGHT_ATTACK.startup + 0.03
        preview.draw(surface)
        draw_text(surface, self.app.fonts[11], "ZERO ASSET PACKS  •  PROCEDURAL ANIMATION", MUTED, (905, 555), "midtop")


class OnlineMenuScene:
    def __init__(self, app):
        self.app = app
        self.background = make_background()
        try:
            self.draft = load_draft(CONFIG_PATH)
        except (OSError, ValueError, TypeError):
            self.draft = TechniqueDraft()
        self.host_ip = "127.0.0.1"
        self.input_active = False
        self.peer = None
        self.sent_technique = False
        self.remote_draft = None
        self.status = "Choose HOST or enter the host IP and JOIN."
        self.host_button = Button((180, 468, 250, 54), "CREATE SERVER", True)
        self.join_button = Button((446, 468, 250, 54), "JOIN SERVER")
        self.edit_button = Button((712, 468, 250, 54), "EDIT TECHNIQUE")
        self.back_button = Button((180, 546, 140, 40), "← BACK")
        self.ip_rect = pygame.Rect(180, 358, 516, 58)

    def close(self):
        if self.peer:
            self.peer.close()

    def begin(self, role):
        self.close()
        address = "0.0.0.0" if role == "host" else self.host_ip.strip()
        if role == "client" and not address:
            self.status = "Enter the host IP address."
            return
        self.peer = NetworkPeer(role, address, DEFAULT_PORT)
        self.peer.start()
        self.sent_technique = False
        self.remote_draft = None
        if role == "host":
            self.status = f"SERVER READY — {local_ip()}:{DEFAULT_PORT} — waiting for player..."
        else:
            self.status = f"CONNECTING TO {address}:{DEFAULT_PORT}..."

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.close()
                self.app.scene = MenuScene(self.app)
            elif self.input_active and event.key == pygame.K_BACKSPACE:
                self.host_ip = self.host_ip[:-1]
            elif self.input_active and event.key == pygame.K_RETURN:
                self.begin("client")
            elif self.input_active and event.unicode in "0123456789.:abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-" and len(self.host_ip) < 64:
                self.host_ip += event.unicode
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.input_active = self.ip_rect.collidepoint(event.pos)
            if self.host_button.rect.collidepoint(event.pos):
                self.begin("host")
            elif self.join_button.rect.collidepoint(event.pos):
                self.begin("client")
            elif self.edit_button.rect.collidepoint(event.pos):
                self.close()
                self.app.scene = CreatorScene(self.app, True, return_online=True)
            elif self.back_button.rect.collidepoint(event.pos):
                self.close()
                self.app.scene = MenuScene(self.app)

    def update(self, dt):
        if not self.peer:
            return
        if self.peer.error:
            self.status = f"CONNECTION ERROR: {self.peer.error}"
            return
        if self.peer.connected.is_set() and not self.sent_technique:
            self.peer.send({"type": "technique", "draft": asdict(self.draft), "protocol": PROTOCOL_VERSION})
            self.sent_technique = True
            self.status = "PLAYER CONNECTED — synchronizing techniques..."
        for message in self.peer.drain():
            if message.get("type") == "hello" and message.get("protocol") != PROTOCOL_VERSION:
                self.status = "GAME VERSIONS DO NOT MATCH."
                self.peer.close()
            elif message.get("type") == "technique":
                self.remote_draft = safe_draft(message.get("draft"))
        if self.sent_technique and self.remote_draft:
            local_tech = TechniqueBalancer.balance(self.draft)
            remote_tech = TechniqueBalancer.balance(self.remote_draft)
            if self.peer.role == "host":
                host_tech, client_tech = local_tech, remote_tech
            else:
                host_tech, client_tech = remote_tech, local_tech
            peer = self.peer
            self.peer = None
            self.app.scene = OnlineFightScene(self.app, host_tech, client_tech, peer, peer.role == "host")

    def draw(self, surface):
        surface.blit(self.background, (0, 0))
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((3, 7, 13, 156))
        surface.blit(overlay, (0, 0))
        draw_text(surface, self.app.fonts[11], "DIRECT-IP MULTIPLAYER / 2 PLAYERS", GREEN, (180, 105))
        draw_text(surface, self.app.fonts[44], "ONLINE HUNTER LOBBY", INK, (180, 132))
        draw_text(surface, self.app.fonts[13], "Host is authoritative. Both players need the same game version.", MUTED, (182, 196))

        panel = pygame.Rect(148, 244, 844, 360)
        draw_round_rect(surface, panel, (12, 21, 31), 22, border_color=LINE)
        draw_text(surface, self.app.fonts[10], "HOST ADDRESS", MUTED, (180, 332))
        draw_round_rect(surface, self.ip_rect, PANEL_2, 12, border_color=AURA_COLORS[0] if self.input_active else LINE)
        shown = self.host_ip + ("|" if self.input_active and pygame.time.get_ticks() % 900 < 450 else "")
        draw_text(surface, self.app.fonts[20], shown, INK, (200, self.ip_rect.centery), "midleft")
        draw_text(surface, self.app.fonts[10], f"PORT {DEFAULT_PORT}", MUTED, (680, self.ip_rect.centery), "midright")

        self.host_button.draw(surface, self.app)
        self.join_button.draw(surface, self.app)
        self.edit_button.draw(surface, self.app)
        self.back_button.draw(surface, self.app)
        status_rect = pygame.Rect(180, 270, 782, 42)
        draw_round_rect(surface, status_rect, (8, 15, 22), 10)
        draw_text(surface, self.app.fonts[11], self.status[:100], AURA_COLORS[0] if not self.peer or not self.peer.error else RED, (196, 282))

        tech = TechniqueBalancer.balance(self.draft)
        draw_text(surface, self.app.fonts[10], "SELECTED TECHNIQUE", MUTED, (1015, 270))
        draw_text(surface, self.app.fonts[18], tech.name, INK, (1015, 294))
        draw_text(surface, self.app.fonts[11], f"{ARCHETYPE_LABELS[tech.archetype]}  •  DMG {tech.damage}  •  AURA {tech.aura_cost}", AURA_COLORS[tech.color_index], (1015, 328))
        draw_text(surface, self.app.fonts[10], "SAME WI-FI: use the host's local IP.", MUTED, (1015, 382))
        draw_text(surface, self.app.fonts[10], "INTERNET: forward TCP 50505 or use a gaming VPN.", MUTED, (1015, 402))


class CreatorScene:
    ARCHETYPES = list(ARCHETYPE_LABELS)

    def __init__(self, app, versus_ai, return_online=False):
        self.app = app
        self.versus_ai = versus_ai
        self.return_online = return_online
        try:
            draft = load_draft(CONFIG_PATH)
        except (OSError, ValueError, TypeError):
            draft = TechniqueDraft()
        self.name = draft.name
        self.archetype_index = self.ARCHETYPES.index(draft.archetype) if draft.archetype in self.ARCHETYPES else 0
        self.values = [draft.power, draft.reach, draft.speed, draft.control]
        self.color_index = draft.color_index
        self.focus_name = False
        self.slider_rects = [pygame.Rect(116, 380 + i * 59, 360, 9) for i in range(4)]
        self.archetype_rects = [pygame.Rect(116 + i * 160, 255, 146, 88) for i in range(4)]
        self.palette_rects = [pygame.Rect(696 + i * 48, 275, 32, 32) for i in range(5)]
        self.mod_button = pygame.Rect(956, 265, 200, 48)
        self.mod_index = -1
        self.name_rect = pygame.Rect(116, 158, 626, 56)
        self.start_button = Button((876, 568, 280, 58), "START DUEL", True)
        self.back_button = Button((116, 642, 132, 38), "← BACK")

    def current_draft(self):
        return TechniqueDraft(
            name=self.name, archetype=self.ARCHETYPES[self.archetype_index],
            power=self.values[0], reach=self.values[1], speed=self.values[2], control=self.values[3],
            color_index=self.color_index,
        )

    def set_slider(self, index, mouse_x):
        rect = self.slider_rects[index]
        t = clamp((mouse_x - rect.left) / rect.width, 0, 1)
        self.values[index] = int(round(1 + t * 9))

    def apply_next_mod(self):
        if not self.app.mod_drafts:
            return
        self.mod_index = (self.mod_index + 1) % len(self.app.mod_drafts)
        draft = self.app.mod_drafts[self.mod_index]
        self.name = draft.name
        self.archetype_index = self.ARCHETYPES.index(draft.archetype)
        self.values = [draft.power, draft.reach, draft.speed, draft.control]
        self.color_index = draft.color_index

    def launch(self):
        draft = self.current_draft()
        try:
            save_draft(CONFIG_PATH, draft)
        except OSError:
            pass
        if self.return_online:
            self.app.scene = OnlineMenuScene(self.app)
        else:
            self.app.scene = FightScene(self.app, TechniqueBalancer.balance(draft), self.versus_ai)

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.app.scene = MenuScene(self.app)
            elif event.key == pygame.K_RETURN:
                self.launch()
            elif self.focus_name and event.key == pygame.K_BACKSPACE:
                self.name = self.name[:-1]
            elif self.focus_name and event.unicode.isprintable() and len(self.name) < 22:
                self.name += event.unicode
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.focus_name = self.name_rect.collidepoint(event.pos)
            for i, rect in enumerate(self.archetype_rects):
                if rect.collidepoint(event.pos):
                    self.archetype_index = i
            for i, rect in enumerate(self.slider_rects):
                if rect.inflate(0, 26).collidepoint(event.pos):
                    self.set_slider(i, event.pos[0])
            for i, rect in enumerate(self.palette_rects):
                if rect.collidepoint(event.pos):
                    self.color_index = i
            if self.mod_button.collidepoint(event.pos):
                self.apply_next_mod()
            if self.start_button.rect.collidepoint(event.pos):
                self.launch()
            if self.back_button.rect.collidepoint(event.pos):
                self.app.scene = MenuScene(self.app)
        elif event.type == pygame.MOUSEMOTION and pygame.mouse.get_pressed()[0]:
            for i, rect in enumerate(self.slider_rects):
                if rect.inflate(0, 28).collidepoint(event.pos):
                    self.set_slider(i, event.pos[0])

    def update(self, dt):
        pass

    def draw(self, surface):
        surface.fill(DARK)
        draw_text(surface, self.app.fonts[11], "TECHNIQUE FORGE / AI ASSISTED", AURA_COLORS[self.color_index], (116, 70))
        draw_text(surface, self.app.fonts[40], "DESIGN YOUR SIGNATURE MOVE", INK, (116, 92))

        draw_text(surface, self.app.fonts[11], "TECHNIQUE NAME", MUTED, (116, 141))
        draw_round_rect(surface, self.name_rect, PANEL_2, 12, border_color=AURA_COLORS[self.color_index] if self.focus_name else LINE)
        shown_name = self.name + ("|" if self.focus_name and pygame.time.get_ticks() % 900 < 450 else "")
        draw_text(surface, self.app.fonts[20], shown_name or "Enter a name...", INK if self.name else MUTED, (136, 174), "midleft")

        draw_text(surface, self.app.fonts[11], "TYP NEN / ARCHETYP", MUTED, (116, 237))
        descriptions = ["BURST", "RANGE", "MOBILITY", "COUNTER"]
        for i, (rect, key) in enumerate(zip(self.archetype_rects, self.ARCHETYPES)):
            selected = i == self.archetype_index
            draw_round_rect(surface, rect, PANEL_2 if selected else PANEL, 13, border_color=AURA_COLORS[self.color_index] if selected else LINE)
            draw_text(surface, self.app.fonts[13], ARCHETYPE_LABELS[key], INK, (rect.centerx, rect.y + 18), "midtop")
            draw_text(surface, self.app.fonts[9], descriptions[i], AURA_COLORS[self.color_index] if selected else MUTED, (rect.centerx, rect.y + 57), "midtop")

        labels = [("POWER", "damage and knockback"), ("REACH", "hit zone"), ("SPEED", "startup and velocity"), ("CONTROL", "recovery and cooldown")]
        for i, (label, desc) in enumerate(labels):
            rect = self.slider_rects[i]
            draw_text(surface, self.app.fonts[11], label, INK, (rect.left, rect.y - 25))
            draw_text(surface, self.app.fonts[9], desc, MUTED, (rect.left + 86, rect.y - 23))
            draw_text(surface, self.app.fonts[15], str(self.values[i]), AURA_COLORS[self.color_index], (rect.right + 30, rect.y - 31), "topright")
            pygame.draw.rect(surface, LINE, rect, border_radius=5)
            fill = pygame.Rect(rect.x, rect.y, int(rect.width * ((self.values[i] - 1) / 9)), rect.height)
            pygame.draw.rect(surface, AURA_COLORS[self.color_index], fill, border_radius=5)
            knob_x = rect.x + int(rect.width * ((self.values[i] - 1) / 9))
            pygame.draw.circle(surface, INK, (knob_x, rect.centery), 8)
            pygame.draw.circle(surface, AURA_COLORS[self.color_index], (knob_x, rect.centery), 5)

        draw_text(surface, self.app.fonts[11], "AURA COLOR", MUTED, (696, 237))
        for i, rect in enumerate(self.palette_rects):
            pygame.draw.circle(surface, AURA_COLORS[i], rect.center, 13)
            if i == self.color_index:
                pygame.draw.circle(surface, INK, rect.center, 18, 2)

        has_mods = bool(self.app.mod_drafts)
        hover_mod = self.mod_button.collidepoint(pygame.mouse.get_pos()) and has_mods
        draw_round_rect(surface, self.mod_button, PANEL_2 if hover_mod else PANEL, 10, border_color=LINE)
        mod_label = f"MODS  {len(self.app.mod_drafts)}  →" if has_mods else "MODS  0"
        draw_text(surface, self.app.fonts[11], mod_label, INK if has_mods else MUTED, self.mod_button.center, "center")

        tech = TechniqueBalancer.balance(self.current_draft())
        panel = pygame.Rect(660, 345, 496, 190)
        draw_round_rect(surface, panel, PANEL, 18, border_color=LINE)
        draw_text(surface, self.app.fonts[11], "AI BALANCE ANALYSIS", MUTED, (688, 367))
        draw_text(surface, self.app.fonts[30], f"{tech.balance_rating}", GREEN, (1116, 360), "topright")
        draw_text(surface, self.app.fonts[9], "FAIR SCORE", MUTED, (1116, 397), "topright")
        stats = [("DMG", tech.damage), ("RANGE", tech.reach), ("START", f"{tech.startup:.2f}s"),
                 ("REC", f"{tech.recovery:.2f}s"), ("AURA", tech.aura_cost), ("CD", f"{tech.cooldown:.1f}s")]
        for i, (label, value) in enumerate(stats):
            x = 688 + (i % 3) * 142
            y = 414 + (i // 3) * 45
            draw_text(surface, self.app.fonts[9], label, MUTED, (x, y))
            draw_text(surface, self.app.fonts[14], value, INK, (x, y + 15))
        note = tech.balance_note.replace("AI: ", "")
        draw_text(surface, self.app.fonts[9], note[:68], AURA_COLORS[self.color_index], (688, 505))

        self.start_button.draw(surface, self.app)
        self.back_button.draw(surface, self.app)
        draw_text(surface, self.app.fonts[10], "ENTER — START", MUTED, (1156, 651), "topright")


class GameApp:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Hunter Duel: Nen Protocol")
        try:
            pygame.display.set_icon(pygame.image.load(str(bundled_path("assets/hunter_duel_icon.png"))))
        except (pygame.error, OSError):
            pass
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()
        pygame.key.set_repeat(330, 42)
        font_names = ["Aptos", "Inter", "Segoe UI", "Arial"]
        available = {name.lower(): name for name in pygame.font.get_fonts()}
        selected = next((available.get(name.lower().replace(" ", "")) for name in font_names if name.lower().replace(" ", "") in available), None)
        self.fonts = {size: pygame.font.SysFont(selected, size, bold=size >= 13) for size in (9, 10, 11, 12, 13, 14, 15, 16, 18, 20, 30, 36, 40, 44, 48, 64, 68)}
        self.mod_drafts, self.mod_warnings = load_mod_drafts(mods_dir())
        self.running = True
        self.scene = MenuScene(self)

    def run(self):
        while self.running:
            dt = min(self.clock.tick(FPS) / 1000.0, 1 / 20)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                else:
                    self.scene.handle_event(event)
            self.scene.update(dt)
            self.scene.draw(self.screen)
            pygame.display.flip()
        pygame.quit()


if __name__ == "__main__":
    GameApp().run()
