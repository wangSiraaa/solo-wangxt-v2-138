"""断面：沿折线采样原地面线 / 设计线，并计算断面上的挖填面积。

断面面积是二维线积分（m²），乘以断面间距才是体积；这里断面法体积
只作为与 TIN 积分、网格法并列的比较口径。
任一面在采样点缺测 -> None，断面线断开绘制，绝不补造高程。
"""
from __future__ import annotations

import numpy as np
from shapely.geometry import LineString, Point

from .models import SectionResult


def sample_section(ground_tin, design_tin,
                   line: list[tuple[float, float]],
                   step: float = 2.0) -> SectionResult:
    ls = LineString(line)
    length = ls.length
    s_list = np.arange(0, length + 1e-9, step)
    xs, ys, zgs, zds = [], [], [], []
    for s in s_list:
        pt = ls.interpolate(float(s))
        x, y = pt.x, pt.y
        xs.append(x)
        ys.append(y)
        # 点须在公共范围内才取值
        if ground_tin.region.covers(pt) and design_tin.region.covers(pt):
            zgs.append(ground_tin.z_at(x, y))
            zds.append(design_tin.z_at(x, y))
        else:
            zgs.append(None)
            zds.append(None)

    cut_area = fill_area = 0.0
    for i in range(len(s_list) - 1):
        ds = s_list[i + 1] - s_list[i]
        g0, g1 = zgs[i], zgs[i + 1]
        d0, d1 = zds[i], zds[i + 1]
        if g0 is None or g1 is None or d0 is None or d1 is None:
            continue
        dz0, dz1 = g0 - d0, g1 - d1
        # 梯形条带：正部(挖)、负部(填)分别积分（线性差值可精确求零点）
        cut_area += _trap_positive(dz0, dz1, ds)
        fill_area += _trap_positive(-dz0, -dz1, ds)

    return SectionResult(
        name=f"断面 {len(line)}点线",
        line=[(float(x), float(y)) for x, y in line],
        s=[float(v) for v in s_list],
        z_ground=[None if v is None else float(v) for v in zgs],
        z_design=[None if v is None else float(v) for v in zds],
        cut_area=float(cut_area), fill_area=float(fill_area),
        length=float(length),
    )


def _trap_positive(h0: float, h1: float, ds: float) -> float:
    """线性高度函数在 [0,ds] 上正部的积分。"""
    eps = 1e-10
    if h0 >= -eps and h1 >= -eps:
        return (max(h0, 0.0) + max(h1, 0.0)) / 2 * ds
    if h0 <= eps and h1 <= eps:
        return 0.0
    # 一正一负：求零点，正部是一个三角形
    t = h0 / (h0 - h1)
    if h0 > 0:
        return h0 * (t * ds) / 2
    return h1 * ((1 - t) * ds) / 2


def grid_sections(ground_tin, design_tin, spacing: float,
                  orientation: str = "x") -> list[SectionResult]:
    """按间距生成一组平行断面（默认南北向，沿 x 方向布站）。"""
    common = ground_tin.region.intersection(design_tin.region)
    minx, miny, maxx, maxy = common.bounds
    results = []
    if orientation == "x":
        for x in np.arange(minx, maxx + 1e-9, spacing):
            line = LineString([(x, miny - 1), (x, maxy + 1)])
            inter = line.intersection(common)
            pts = _line_endpoints(inter)
            if pts:
                r = sample_section(ground_tin, design_tin, pts)
                r.name = f"X={x:.2f}m 断面"
                results.append(r)
    else:
        for y in np.arange(miny, maxy + 1e-9, spacing):
            line = LineString([(minx - 1, y), (maxx + 1, y)])
            inter = line.intersection(common)
            pts = _line_endpoints(inter)
            if pts:
                r = sample_section(ground_tin, design_tin, pts)
                r.name = f"Y={y:.2f}m 断面"
                results.append(r)
    return results


def section_volume(sections: list[SectionResult]) -> dict:
    """相邻断面面积按梯形公式过渡乘断面间距（端部半间距）。

    断面法只在两端断面间线性过渡，与 TIN 积分、网格法并列供比较，
    断面线必须沿同一方向、桩号间距已知。
    """
    if not sections:
        return {"cut": 0.0, "fill": 0.0, "length": 0.0, "n": 0}
    cut = fill = 0.0
    for i in range(len(sections) - 1):
        s0, s1 = sections[i], sections[i + 1]
        # 间距取两条平行断面的中线间距：用端点中点距离近似
        m0x = (s0.line[0][0] + s0.line[-1][0]) / 2
        m0y = (s0.line[0][1] + s0.line[-1][1]) / 2
        m1x = (s1.line[0][0] + s1.line[-1][0]) / 2
        m1y = (s1.line[0][1] + s1.line[-1][1]) / 2
        d = np.hypot(m1x - m0x, m1y - m0y)
        cut += (s0.cut_area + s1.cut_area) / 2 * d
        fill += (s0.fill_area + s1.fill_area) / 2 * d
    return {"cut": float(cut), "fill": float(fill),
            "length": float(len(sections) - 1), "n": len(sections)}


def _line_endpoints(geom):
    """从线与区域的交点中取出最长的一段线。"""
    if geom.is_empty:
        return None
    lines = []
    if geom.geom_type == "LineString":
        lines = [geom]
    elif geom.geom_type in ("MultiLineString", "GeometryCollection"):
        lines = [g for g in geom.geoms if g.geom_type == "LineString"]
    lines = [g for g in lines if g.length > 1e-9]
    if not lines:
        return None
    best = max(lines, key=lambda g: g.length)
    c = best.coords
    return [(c[0][0], c[0][1]), (c[-1][0], c[-1][1])]
