from dataclasses import dataclass


@dataclass
class Roi:
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0

    @property
    def enabled(self) -> bool:
        return self.w > 0 and self.h > 0

    def clamp(self, width: int, height: int) -> "Roi":
        x = max(0, min(self.x, width))
        y = max(0, min(self.y, height))
        w = max(0, min(self.w, width - x))
        h = max(0, min(self.h, height - y))
        return Roi(x=x, y=y, w=w, h=h)
