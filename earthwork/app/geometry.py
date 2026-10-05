"""2D 几何辅助：环定向、多边形构建、点在三角形内的重心坐标。"""
from __future__ import annotations

import numpy as np
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.polygon import orient

_EPS_AREA = 1e-9


def signed_area(coords: np.ndarray) -> float:
    """鞋带公式，coords 形状 (n,2)，不闭合。"""
    x, y = coords[:, 0], coords[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def as_ccw(coords) -> np.ndarray:
    c = np.asarray(coords, dtype=float)
    if len(c) > 1 and np.allclose(c[0], c[-1]):
        c = c[:-1]
    if signed_area(c) < 0:
        c = c[::-1]
    return c


def build_region(outer: list | None,
                 holes: list[list] | None = None,
                 no_data: list[list] | None = None) -> Polygon:
    """构建计算范围多边形。

    outer=None 时调用方需先用点集凸包。
    holes / no_data 都作为洞（边界孔洞明确不计算；缺测区按“不外推”原则同样扣除）。
    Shapely 要求外环逆时针、洞顺时针，orient 统一处理。
    """
    if outer is None:
        raise ValueError("outer ring required")
    outer_ring = as_ccw(outer)
    inner = []
    for h in (holes or []):
        hc = as_ccw(h)
        if signed_area(hc) > 0:
            hc = hc[::-1]
        inner.append(np.asarray(hc, dtype=float))
    for h in (no_data or []):
        hc = as_ccw(h)
        if signed_area(hc) > 0:
            hc = hc[::-1]
        inner.append(np.asarray(hc, dtype=float))
    poly = Polygon(outer_ring, inner)
    if not poly.is_valid:
        poly = poly.buffer(0)
    return orient(poly, sign=1.0)


def split_polygons(geom) -> list[Polygon]:
    """intersection 可能返回 Polygon / MultiPolygon / GeometryCollection。"""
    out: list[Polygon] = []
    if geom.is_empty:
        return out
    if geom.geom_type == "Polygon":
        if geom.area > _EPS_AREA:
            out.append(geom)
    elif geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        for g in geom.geoms:
            if g.geom_type == "Polygon" and g.area > _EPS_AREA:
                out.append(g)
    return out


def barycentric(p: np.ndarray, a: np.ndarray, b: np.ndarray, c: np.ndarray):
    """p 相对三角形 abc 的重心坐标 (w0,w1,w2)。"""
    v0 = b - a
    v1 = c - a
    v2 = p - a
    d00 = v0 @ v0
    d01 = v0 @ v1
    d11 = v1 @ v1
    d20 = v2 @ v0
    d21 = v2 @ v1
    denom = d00 * d11 - d01 * d01
    if abs(denom) < 1e-18:
        return None
    w1 = (d11 * d20 - d01 * d21) / denom
    w2 = (d00 * d21 - d01 * d20) / denom
    w0 = 1.0 - w1 - w2
    return w0, w1, w2


def tri_quality(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> tuple[float, float]:
    """返回 (面积, 质量 2r/R)。等边=1，退化->0。"""
    e1 = np.hypot(*(b - a))
    e2 = np.hypot(*(c - b))
    e3 = np.hypot(*(a - c))
    area = 0.5 * abs((b[0] - a[0]) * (c[1] - a[1])
                     - (c[0] - a[0]) * (b[1] - a[1]))
    s = (e1 + e2 + e3) / 2
    if area <= 1e-12 or s <= 0:
        return area, 0.0
    r = area / s
    R = e1 * e2 * e3 / (4 * area) if area > 0 else 1e18
    return area, min(1.0, 2 * r / R)
