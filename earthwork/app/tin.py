"""限定范围内的 TIN。

做法（边界外不擅自外推）：
  1. SciPy Delaunay 对全部二维点做剖分（qhull）；
  2. 每个三角片与 Shapely 范围多边形求交，保留落在范围内的部分；
  3. 交点处的高程来自该三角片自身的线性插值——只沿已有三角片边/面内插，
     绝不对边界外区域做任何外推。

裁剪后的碎片：("tri", tri_idx, None) 完整三角片；("frag", tri_idx, 多边形) 裁剪残片。
高程查询 z_at(x,y) 仍在完整 Delaunay 三角网上进行（qhull 保证凸包内定位），
返回 None 表示凸包外（无数据，不猜测）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.spatial import ConvexHull, Delaunay
from shapely.geometry import Polygon as ShPolygon

from .geometry import barycentric, build_region, signed_area, split_polygons, tri_quality


@dataclass
class SurfaceTIN:
    name: str                       # "ground" / "design"
    coords: np.ndarray              # (n,2)
    z: np.ndarray                   # (n,)
    tri: Delaunay
    region: ShPolygon
    pieces: list = field(default_factory=list)  # [("tri",i,None) | ("frag",i,ShPolygon)]
    n_clipped: int = 0
    degenerate: list = field(default_factory=list)  # (simplices, area, quality)

    @property
    def extent(self):
        return (float(self.coords[:, 0].min()), float(self.coords[:, 1].min()),
                float(self.coords[:, 0].max()), float(self.coords[:, 1].max()))

    def simplices_xy(self, t: int) -> np.ndarray:
        idx = self.tri.simplices[t]
        return self.coords[idx]

    def locate(self, x: float, y: float, tol: float = 1e-6):
        """返回 (三角片号, (w0,w1,w2))；凸包外返回 None。

        tol：允许点越出三角形边的距离容差（米）。裁剪共线交点可能因缓冲
        （1e-7 m）落在凸包外侧，此容差内夹紧到边上，不当作“外推”。
        """
        p = np.array([x, y])
        t = self.tri.find_simplex(p)
        if t < 0:
            return None
        idx = self.tri.simplices[t]
        a, b, c = self.coords[idx[0]], self.coords[idx[1]], self.coords[idx[2]]
        w = barycentric(p, a, b, c)
        if w is None:
            return None
        w0, w1, w2 = w
        edge_scale = max(np.hypot(*(b - a)), np.hypot(*(c - a)), 1.0)
        # 重心权重越界量换算成大致距离，超出 tol 才判为凸包外（不外推）
        if min(w0, w1, w2) < -tol / edge_scale:
            return None
        w0, w1, w2 = (max(w0, 0.0), max(w1, 0.0), max(w2, 0.0))
        s = w0 + w1 + w2
        return t, (w0 / s, w1 / s, w2 / s)

    def z_at(self, x: float, y: float) -> float | None:
        loc = self.locate(x, y)
        if loc is None:
            return None
        t, (w0, w1, w2) = loc
        i0, i1, i2 = self.tri.simplices[t]
        return float(w0 * self.z[i0] + w1 * self.z[i1] + w2 * self.z[i2])

    def z_on_tri(self, t: int, xy: np.ndarray) -> np.ndarray:
        """已知点在三角片 t 内（含边），向量化求高程。"""
        i0, i1, i2 = self.tri.simplices[t]
        a, b, c = self.coords[i0], self.coords[i1], self.coords[i2]
        v0, v1 = b - a, c - a
        v2 = xy - a
        d00, d01, d11 = v0 @ v0, v0 @ v1, v1 @ v1
        denom = d00 * d11 - d01 * d01
        w1 = (d11 * (v2 @ v0) - d01 * (v2 @ v1)) / denom
        w2 = (d00 * (v2 @ v1) - d01 * (v2 @ v0)) / denom
        w0 = 1 - w1 - w2
        return w0 * self.z[i0] + w1 * self.z[i1] + w2 * self.z[i2]


def _ring_simplify(coords: np.ndarray) -> np.ndarray:
    """去掉裁剪交点序列中近重复的连续点。"""
    keep = [coords[0]]
    for p in coords[1:]:
        if np.hypot(*(p - keep[-1])) > 1e-7:
            keep.append(p)
    if len(keep) > 1 and np.hypot(*(keep[0] - keep[-1])) <= 1e-7:
        keep.pop()
    return np.asarray(keep)


def build_tin(name: str,
              coords: np.ndarray,
              z: np.ndarray,
              outer: list | None,
              holes: list[list] | None,
              no_data: list[list] | None = None,
              boundary_simplify: bool = True) -> SurfaceTIN:
    """构建限定 TIN。outer 为 None 时用凸包。"""
    coords = np.asarray(coords, dtype=float)
    z = np.asarray(z, dtype=float)
    if len(coords) < 3:
        raise ValueError(f"{name}: 至少需要 3 个点才能构成 TIN")

    tri = Delaunay(coords, qhull_options="Qbb Qc Qz Q12")
    ch = ConvexHull(coords)
    # 严格按点集凸包裁剪：凸包外无测点，不膨胀、不外推；
    # 共线数值缝隙由 overlay 定位侧的小容差吸收。
    hull_poly = ShPolygon(coords[ch.vertices])

    if outer is None:
        outer = coords[ch.vertices]
    declared = build_region(outer, holes, no_data)
    region = declared.intersection(hull_poly)
    if region.is_empty:
        raise ValueError(f"{name}: 声明边界与测点凸包没有交集，无法构建 TIN")

    tin = SurfaceTIN(name=name, coords=coords, z=z, tri=tri, region=region)

    # 先做三角片退化检查（完整剖分上，便于列出问题片）
    for t in range(len(tri.simplices)):
        i0, i1, i2 = tri.simplices[t]
        area, quality = tri_quality(coords[i0], coords[i1], coords[i2])
        if area < 1e-9 or quality < 1e-6:
            tin.degenerate.append(([int(i0), int(i1), int(i2)],
                                   float(area), float(quality)))

    region_grown = region.buffer(1e-7)  # 容差吸收边界共线缝隙
    for t in range(len(tri.simplices)):
        pts = tin.simplices_xy(t)
        tp = ShPolygon(pts)
        if region_grown.covers(tp):
            tin.pieces.append(("tri", int(t), None))
            continue
        inter = tp.intersection(region)
        parts = split_polygons(inter)
        if not parts:
            tin.n_clipped += 1
            continue
        for p in parts:
            # 保留完整多边形（含洞环）；裁剪残片面积过小（数值毛刺）则丢弃
            if p.area < 1e-7:
                continue
            tin.pieces.append(("frag", int(t), p))
        tin.n_clipped += 1
    return tin
