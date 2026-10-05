"""三角片上挖、填体积的精确积分。

原地面与设计面在叠加单元内都是平面，故差值 dz = z_ground - z_design 在
每个耳三角片上是仿射函数（线性面）。零挖填线把三角片分成 dz>=0 / dz<0
两部分，用半平面裁剪求多边形，再按
    ∫_P dz dA = area(P) * (dz 在 P 顶点值之和) / 3
精确积分（线性函数多边形积分公式），挖、填分别累计，绝不以净体积合并。
"""
from __future__ import annotations

import numpy as np

from .geometry import signed_area

_EPS = 1e-10


def _clip_positive(verts: np.ndarray, dz: np.ndarray) -> np.ndarray:
    """Sutherland-Hodgman 将凸多边形（三角形）裁剪到 dz>=0 一侧。"""
    out: list[np.ndarray] = []
    n = len(verts)
    for i in range(n):
        s_xy, s_d = verts[i - 1], dz[i - 1]
        e_xy, e_d = verts[i], dz[i]
        s_in, e_in = s_d >= -_EPS, e_d >= -_EPS
        if s_in and e_in:
            out.append(e_xy)
        elif s_in and not e_in:
            t = s_d / (s_d - e_d) if abs(s_d - e_d) > _EPS else 0.0
            out.append(s_xy + t * (e_xy - s_xy))
        elif not s_in and e_in:
            t = s_d / (s_d - e_d) if abs(s_d - e_d) > _EPS else 0.0
            out.append(s_xy + t * (e_xy - s_xy))
            out.append(e_xy)
    if not out:
        return np.empty((0, 2))
    return np.asarray(out)


def _fan_integral(poly: np.ndarray, dz_v: np.ndarray) -> tuple[float, float]:
    """对裁剪后 dz>=0 的凸多边形扇划分，返回 (面积, ∫dz)。"""
    if len(poly) < 3:
        return 0.0, 0.0
    total_area = 0.0
    integ = 0.0
    for i in range(1, len(poly) - 1):
        tri = np.vstack([poly[0], poly[i], poly[i + 1]])
        a = abs(signed_area(tri))
        if a < _EPS:
            continue
        total_area += a
        integ += a * (dz_v[0] + dz_v[i] + dz_v[i + 1]) / 3.0
    return total_area, integ


def tri_cut_fill(verts: np.ndarray,
                 dz: np.ndarray) -> tuple[float, float, float, float]:
    """一个三角片的 (挖方面积, 填方面积, 挖方体积, 填方体积)。

    dz>=0 为挖（原地面高于设计面）。体积单位 m³，面积单位 m²。
    """
    a = abs(signed_area(verts))
    if a < _EPS:
        return 0.0, 0.0, 0.0, 0.0

    # 全挖 / 全填的简单情形
    if np.all(dz >= -_EPS):
        v = a * float(np.sum(np.maximum(dz, 0.0))) / 3.0
        return a, 0.0, v, 0.0
    if np.all(dz <= _EPS):
        v = a * float(np.sum(-np.minimum(dz, 0.0))) / 3.0
        return 0.0, a, 0.0, v

    # 跨零：裁剪出挖方部分
    pos = _clip_positive(verts, dz)
    pos_area = 0.0
    cut_v = 0.0
    if len(pos) >= 3:
        # 裁剪点上的 dz：原始点直接取；交点由构造知 dz≈0
        dpos = np.zeros(len(pos))
        for i, p in enumerate(pos):
            for j, q in enumerate(verts):
                if np.hypot(*(p - q)) < 1e-8:
                    dpos[i] = dz[j]
                    break
        pos_area, cut_v = _fan_integral(pos, dpos)

    signed_total = a * float(np.sum(dz)) / 3.0   # 挖 - 填
    fill_v = cut_v - signed_total                # 由 signed = cut - fill 反解
    fill_v = max(fill_v, 0.0)
    cut_v = max(cut_v, 0.0)
    fill_area = a - pos_area
    return pos_area, fill_area, cut_v, fill_v
