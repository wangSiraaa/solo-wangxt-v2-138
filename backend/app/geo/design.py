"""设计面：平面、规则网格、或设计点 TIN。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from .tin import TINSurface, build_constrained_tin


@dataclass
class PlaneDesign:
    """z = a*x + b*y + c。平面坡地可手算案例使用。"""
    a: float
    b: float
    c: float

    @property
    def coeff(self):
        return (self.a, self.b, self.c)

    def z(self, x: float, y: float) -> float:
        return self.a * x + self.b * y + self.c

    def describe(self) -> dict:
        slope = (self.a ** 2 + self.b ** 2) ** 0.5
        azimuth = (90 - np.degrees(np.arctan2(-self.b, self.a))) % 360
        return {
            "kind": "plane",
            "formula": f"z = {self.a:.6g}*x {self.b:+.6g}*y {self.c:+.6g}",
            "slope_percent": round(slope * 100, 4),
            "slope_deg": round(np.degrees(np.arctan(slope)), 4),
            "azimuth_deg": round(azimuth, 3),
        }


def build_design_surface(design: dict, domain, quality_fn=None):
    """按 design.kind 构造可积分对象。

    design:
      {"kind": "plane", "a","b","c"}
      {"kind": "points", "points": [...]}        -> 限定 TIN
      {"kind": "grid", "origin":[x,y], "dx","dy","nx","ny","z":[...]}
    """
    kind = design.get("kind")
    if kind == "plane":
        return PlaneDesign(float(design["a"]), float(design["b"]), float(design["c"])), "plane"

    if kind == "points":
        pts = design["points"]
        keep = None
        if quality_fn is not None:
            qc = quality_fn(pts, domain)
            keep = qc["keep"]
        return TINSurface(build_constrained_tin(pts, domain, keep)), "tin"

    if kind == "grid":
        ox, oy = design["origin"]
        dx, dy = float(design["dx"]), float(design["dy"])
        nx, ny = int(design["nx"]), int(design["ny"])
        z = np.asarray(design["z"], dtype=float).reshape(ny, nx)
        pts = []
        for j in range(ny):
            for i in range(nx):
                if not np.isfinite(z[j, i]):
                    continue  # 网格缺测单元：不造点
                pts.append({
                    "id": f"d_{i}_{j}",
                    "x": ox + i * dx,
                    "y": oy + j * dy,
                    "z": float(z[j, i]),
                })
        return TINSurface(build_constrained_tin(pts, domain)), "tin"

    raise ValueError(f"未知设计面类型: {kind}")
