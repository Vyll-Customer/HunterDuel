"""HUNTER DUEL: Nen Protocol — a clean procedural 2D fighting prototype."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

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

    skyline = [(0, 455), (105, 430), (180, 448), (265, 400), (350, 438), (445, 392),
               (560, 445), (670, 410), (790, 445), (895, 390), (1030, 430), (1150, 402), (1280, 440)]
    pygame.draw.polygon(surface, (13, 24, 34), skyline + [(WIDTH, HEIGHT), (0, HEIGHT)])
    for x in range(28, WIDTH, 73):
        y = 455 - ((x * 13) % 62)
        pygame.draw.rect(surface, (24, 53, 64), (x, y, 3, 12), border_radius=2)

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
        self.vy = -min(170, knockback * 0.32)
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

        def limb(start, delta, color, width=11):
            end = pygame.Vector2(x + delta[0], floor - (140 - delta[1]) - bob)
            mid = (start + end) * 0.5 + pygame.Vector2(self.facing * 4, 7)
            pygame.draw.line(surface, darken(color, 0.24), start, mid, width + 4)
            pygame.draw.line(surface, color, start, mid, width)
            pygame.draw.line(surface, darken(color, 0.24), mid, end, width + 3)
            pygame.draw.line(surface, color, mid, end, width - 1)
            pygame.draw.circle(surface, lighten(color, 0.25), end, width // 2)

        limb(hip, leg_back, darken(self.color, 0.2), 12)
        limb(shoulder, arm_back, darken(self.color, 0.13), 10)

        body_points = [
            (shoulder.x - 17, shoulder.y - 4),
            (shoulder.x + 18, shoulder.y - 4),
            (hip.x + 18, hip.y + 5),
            (hip.x - 17, hip.y + 5),
        ]
        pygame.draw.polygon(surface, darken(self.color, 0.34), body_points)
        inner = [(px + (2 if px < x else -2), py + 2) for px, py in body_points]
        pygame.draw.polygon(surface, self.color, inner)
        pygame.draw.line(surface, self.accent, (shoulder.x - 13, shoulder.y + 8), (hip.x + 8, hip.y - 1), 5)

        limb(hip, leg_front, self.color, 12)
        limb(shoulder, arm_front, self.color, 10)

        pygame.draw.circle(surface, darken(self.color, 0.40), head, 21)
        pygame.draw.circle(surface, lighten(self.color, 0.14), (head.x, head.y + 1), 18)
        eye_x = head.x + self.facing * 8
        pygame.draw.line(surface, aura_color, (eye_x - self.facing * 2, head.y - 2), (eye_x + self.facing * 6, head.y - 2), 3)
        pygame.draw.arc(surface, darken(self.color, 0.5), (head.x - 19, head.y - 20, 38, 27), math.pi, math.tau, 6)

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
            name="Lustrzany Węzeł",
            archetype=random.choice(["impact", "mobility", "counter"]),
            power=random.randint(4, 8), reach=random.randint(3, 8),
            speed=random.randint(4, 8), control=random.randint(4, 8), color_index=3,
        )
        rival_tech = TechniqueBalancer.balance(rival_draft)
        self.p1 = Fighter(330, (36, 94, 132), AURA_COLORS[technique.color_index], "ŁOWCA 01", technique)
        self.p2 = Fighter(950, (118, 48, 79), AURA_COLORS[rival_tech.color_index], "ŁOWCA 02" if not versus_ai else "ECHO AI", rival_tech)
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
                block=keys[pygame.K_s], dash=pygame.K_q in self.just_pressed,
                light=pygame.K_f in self.just_pressed, heavy=pygame.K_g in self.just_pressed,
                special=pygame.K_h in self.just_pressed,
            )
        return Intent(
            left=keys[pygame.K_LEFT], right=keys[pygame.K_RIGHT], jump=pygame.K_UP in self.just_pressed,
            block=keys[pygame.K_DOWN], dash=pygame.K_RSHIFT in self.just_pressed,
            light=pygame.K_j in self.just_pressed, heavy=pygame.K_k in self.just_pressed,
            special=pygame.K_l in self.just_pressed,
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
            self.p1.update(dt, p1_intent, self.p2, self.afterimages)
            self.p2.update(dt, p2_intent, self.p1, self.afterimages)
            self.resolve_body_collision()
            self.apply_attack(self.p1, self.p2)
            self.apply_attack(self.p2, self.p1)
            self.update_projectiles(dt)
            if self.p1.health <= 0 or self.p2.health <= 0 or self.round_time <= 0:
                self.finished = True
                self.finish_timer = 0
        else:
            self.finish_timer += dt

        for p in self.particles:
            p.update(dt)
        for a in self.afterimages:
            a.update(dt)
        self.particles = [p for p in self.particles if p.life > 0]
        self.afterimages = [a for a in self.afterimages if a.life > 0]
        self.shake *= 0.83 ** (dt * 60)
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
        draw_text(surface, self.app.fonts[10], "RUNDA 01", MUTED, (WIDTH // 2, 81), "midtop")

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
                title, color = "RUNDA 01", INK
            else:
                title, color = "WALCZ!", AURA_COLORS[self.technique.color_index]
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
            draw_text(surface, self.app.fonts[16], "KONIEC RUNDY", GOLD, (WIDTH // 2, 255), "midtop")
            draw_text(surface, self.app.fonts[48], winner, INK, (WIDTH // 2, 286), "midtop")
            draw_text(surface, self.app.fonts[14], "R — REWANŻ     ESC — PAUZA / MENU", MUTED, (WIDTH // 2, 358), "midtop")

        if self.paused:
            overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            overlay.fill((4, 8, 14, 210))
            surface.blit(overlay, (0, 0))
            draw_text(surface, self.app.fonts[44], "PAUZA", INK, (WIDTH // 2, 230), "midtop")
            draw_text(surface, self.app.fonts[14], "ESC — WRÓĆ DO WALKI", MUTED, (WIDTH // 2, 300), "midtop")
            button = pygame.Rect(WIDTH // 2 - 110, 350, 220, 48)
            mouse = pygame.mouse.get_pos()
            draw_round_rect(surface, button, PANEL_2 if button.collidepoint(mouse) else PANEL, 12, border_color=LINE)
            draw_text(surface, self.app.fonts[14], "MENU GŁÓWNE", INK, button.center, "center")
            if pygame.mouse.get_pressed()[0] and button.collidepoint(mouse):
                self.app.scene = MenuScene(self.app)


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
            Button((96, 385, 284, 56), "POJEDYNEK Z AI", True),
            Button((96, 453, 284, 56), "LOKALNE 1V1"),
            Button((96, 521, 284, 48), "WYJŚCIE"),
        ]

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.buttons[0].rect.collidepoint(event.pos):
                self.app.scene = CreatorScene(self.app, True)
            elif self.buttons[1].rect.collidepoint(event.pos):
                self.app.scene = CreatorScene(self.app, False)
            elif self.buttons[2].rect.collidepoint(event.pos):
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
        draw_text(surface, self.app.fonts[14], "Stwórz technikę. AI ustali ramy. Ty wygrywasz pojedynek.", INK, (97, 317))
        for button in self.buttons:
            button.draw(surface, self.app)

        # Decorative fighter card on the right.
        card = pygame.Rect(660, 95, 490, 510)
        draw_round_rect(surface, card, (13, 22, 33), 28, border_color=LINE)
        draw_text(surface, self.app.fonts[11], "SYSTEM WALKI / BUILD 0.9", MUTED, (694, 127))
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


class CreatorScene:
    ARCHETYPES = list(ARCHETYPE_LABELS)

    def __init__(self, app, versus_ai):
        self.app = app
        self.versus_ai = versus_ai
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
        self.start_button = Button((876, 568, 280, 58), "URUCHOM POJEDYNEK", True)
        self.back_button = Button((116, 642, 132, 38), "← WRÓĆ")

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
        draw_text(surface, self.app.fonts[11], "KREATOR TECHNIKI / AI ASSISTED", AURA_COLORS[self.color_index], (116, 70))
        draw_text(surface, self.app.fonts[40], "ZAPROJEKTUJ SWÓJ RUCH", INK, (116, 92))

        draw_text(surface, self.app.fonts[11], "NAZWA TECHNIKI", MUTED, (116, 141))
        draw_round_rect(surface, self.name_rect, PANEL_2, 12, border_color=AURA_COLORS[self.color_index] if self.focus_name else LINE)
        shown_name = self.name + ("|" if self.focus_name and pygame.time.get_ticks() % 900 < 450 else "")
        draw_text(surface, self.app.fonts[20], shown_name or "Wpisz nazwę...", INK if self.name else MUTED, (136, 174), "midleft")

        draw_text(surface, self.app.fonts[11], "TYP NEN / ARCHETYP", MUTED, (116, 237))
        descriptions = ["BURST", "DYSTANS", "MOBILNOŚĆ", "KONTRA"]
        for i, (rect, key) in enumerate(zip(self.archetype_rects, self.ARCHETYPES)):
            selected = i == self.archetype_index
            draw_round_rect(surface, rect, PANEL_2 if selected else PANEL, 13, border_color=AURA_COLORS[self.color_index] if selected else LINE)
            draw_text(surface, self.app.fonts[13], ARCHETYPE_LABELS[key], INK, (rect.centerx, rect.y + 18), "midtop")
            draw_text(surface, self.app.fonts[9], descriptions[i], AURA_COLORS[self.color_index] if selected else MUTED, (rect.centerx, rect.y + 57), "midtop")

        labels = [("MOC", "obrażenia i knockback"), ("ZASIĘG", "strefa trafienia"), ("SZYBKOŚĆ", "startup i prędkość"), ("KONTROLA", "recovery i cooldown")]
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

        draw_text(surface, self.app.fonts[11], "KOLOR AURY", MUTED, (696, 237))
        for i, rect in enumerate(self.palette_rects):
            pygame.draw.circle(surface, AURA_COLORS[i], rect.center, 13)
            if i == self.color_index:
                pygame.draw.circle(surface, INK, rect.center, 18, 2)

        has_mods = bool(self.app.mod_drafts)
        hover_mod = self.mod_button.collidepoint(pygame.mouse.get_pos()) and has_mods
        draw_round_rect(surface, self.mod_button, PANEL_2 if hover_mod else PANEL, 10, border_color=LINE)
        mod_label = f"MODY  {len(self.app.mod_drafts)}  →" if has_mods else "MODY  0"
        draw_text(surface, self.app.fonts[11], mod_label, INK if has_mods else MUTED, self.mod_button.center, "center")

        tech = TechniqueBalancer.balance(self.current_draft())
        panel = pygame.Rect(660, 345, 496, 190)
        draw_round_rect(surface, panel, PANEL, 18, border_color=LINE)
        draw_text(surface, self.app.fonts[11], "ANALIZA BALANSU AI", MUTED, (688, 367))
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
        self.fonts = {size: pygame.font.SysFont(selected, size, bold=size >= 13) for size in (9, 10, 11, 12, 13, 14, 15, 16, 20, 30, 36, 40, 44, 48, 64, 68)}
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
