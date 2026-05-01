"""Lightweight particle system for visual feedback."""
import pygame
import random
import math

class Particle:
    __slots__ = ("x","y","vx","vy","life","max_life","size","color","glow")

    def __init__(self, x, y, color, size=4, speed=120, glow=False):
        angle = random.uniform(0, math.tau)
        spd   = random.uniform(speed * 0.4, speed)
        self.x, self.y   = float(x), float(y)
        self.vx           = math.cos(angle) * spd
        self.vy           = math.sin(angle) * spd - random.uniform(20, 60)
        self.life         = 1.0
        self.max_life     = random.uniform(0.4, 0.9)
        self.size         = size
        self.color        = color
        self.glow         = glow

    def update(self, dt):
        self.x   += self.vx * dt
        self.y   += self.vy * dt
        self.vy  += 180 * dt   # gravity
        self.life -= dt / self.max_life
        return self.life > 0

    def draw(self, surf):
        alpha = max(0, min(255, int(self.life * 255)))
        r, g, b = self.color
        size = max(1, int(self.size * self.life))
        if self.glow:
            gsurf = pygame.Surface((size*4, size*4), pygame.SRCALPHA)
            pygame.draw.circle(gsurf, (r, g, b, alpha//3), (size*2, size*2), size*2)
            surf.blit(gsurf, (int(self.x)-size*2, int(self.y)-size*2),
                      special_flags=pygame.BLEND_RGBA_ADD)
        pygame.draw.circle(surf, (r, g, b), (int(self.x), int(self.y)), size)


class ParticleSystem:
    def __init__(self):
        self._particles = []

    def burst(self, x, y, color, count=12, size=5, speed=150, glow=True):
        for _ in range(count):
            self._particles.append(Particle(x, y, color, size, speed, glow))

    def stream(self, x, y, color, count=3, size=3, speed=60):
        for _ in range(count):
            self._particles.append(Particle(x, y, color, size, speed, False))

    def update(self, dt):
        self._particles = [p for p in self._particles if p.update(dt)]

    def draw(self, surf):
        for p in self._particles:
            p.draw(surf)

    def clear(self):
        self._particles.clear()
