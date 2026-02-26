import math


class Vec2:
    def __init__(self, x: float = 0, y: float = 0):
        self.x = x
        self.y = y

    def __add__(self, other):
        return Vec2(self.x + other.x, self.y + other.y)
    def __sub__(self, other):
        return Vec2(self.x - other.x, self.y - other.y)
    def __mul__(self, other):
        return Vec2(self.x * other.x, self.y * other.y)
    def __truediv__(self, other):
        return Vec2(self.x / other.x, self.y / other.y)
    def __floordiv__(self, other):
        return Vec2(self.x // other.x, self.y // other.y)

    def __neg__(self):
        return Vec2(-self.x, -self.y)

class Rect:
    def __init__(self, start: Vec2 = Vec2(math.inf, math.inf), end: Vec2 = Vec2(-math.inf, -math.inf)):
        self.start = start
        self.end = end

    def size(self):
        return Vec2(abs(self.end.x - self.start.x), abs(self.end.y - self.start.y))

    def reset(self):
        self.start.x = math.inf
        self.start.y = math.inf
        self.end.x = -math.inf
        self.end.y = -math.inf