"""挖方 / 填方体积积分。

定义（工程惯例）：在任意微元 dA 上
    diff = z_ground - z_design
    diff > 0  →  该微元为挖方（原地面高于设计面，需要挖掉）
    diff < 0  →  该微元填方（原地面低于设计面，需要填上）

体积 = 在“两张曲面共同覆盖、且位于计量边界内”的区域上，分别对
max(diff,0)、max(-diff,0) 积分。净体积 V_cut - V_fill 仅作附带输出，
绝不能用它掩盖大量同时存在的挖填。

积分方法（TIN 精确法）：
取原地面 TIN 与设计面 TIN 的三角形多边形求交；在每对相交三角形的交集
多边形上，两张曲面都是各自三角形上的仿射平面，因此 diff 也是仿射函数。
用多边形三角剖分（耳切）得到积分单元，在每个小三角形上对仿射函数做
精确一次矩积分：
    ∫_T f dA = area_T * (f1 + f2 + f3) / 3   （顶点函数值的算术平均）

对 f=max(diff,0) 这类折拐函数，先把 diff=0 的等值线（折线）插入交集
多边形，再耳切——即两三角形交线多边形 + 零线裁剪，保证挖填分段精确。

另提供规则网格法做精度对比（网格越细趋近 TIN 精确值），以及断面法。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Callable

import numpy as np
from shapely.geometry import Polygon as SPoly
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

from .tin import TINSurface


# ---------------------------------------------------------------------------
# 平面三角片上的仿射值求值
# ---------------------------------------------------------------------------

def _affine_on_triangle(verts3: np.ndarray):
    """给定 3 个 (x,y,z) 顶点，返回 f(x,y)=ax+by+c。"""
    (x1, y1, z1), (x2, y2, z2), (x3, y3, z3) = verts3
    den = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
    if abs(den) < 1e-15:
        return None
    a = ((y2 - y3) * (z1 - z3) + (z3 - z2) * (y1 - y3)) / den
    b = ((x3 - x2) * (z1 - z3) + (x1 - x3) * (z2 - z3)) / den
    c = z1 - a * x1 - b * y1
    return a, b, c


def _ear_triangulate(poly: SPoly):
    """对凸/简单多边形做耳切，返回三角形顶点数组列表。

    Shapely 交集多边形可能带洞；调用前应先用 zeroline 分割并保证简单。
    """
    from shapely.geometry.polygon import orient
    poly = orient(poly, sign=1.0)
    ring = np.array(poly.exterior.coords[:-1])
    tris = []
    idx = list(range(len(ring)))
    guard = 0
    while len(idx) > 2 and guard < len(ring) * 3 + 10:
        guard += 1
        clipped = False
        for k in range(len(idx)):
            i, j, n = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            a, b, cpt = ring[i], ring[j], ring[n]
            # 凸（外环逆时针）且耳内无其他顶点
            cross = (b[0] - a[0]) * (cpt[1] - a[1]) - (b[1] - a[1]) * (cpt[0] - a[0])
            if cross <= 0:
                continue
            ear = SPoly([a, b, cpt])
            if any(
                m not in (i, j, n) and ear.covers(Point(ring[m]))
                for m in idx
            ):
                continue
            tris.append((a, b, cpt))
            idx.pop(k)
            clipped = True
            break
        if not clipped:
            # 退化环（自交/共线噪声）：扇形兜底
            a = ring[idx[0]]
            for k in range(1, len(idx) - 1):
                tris.append((a, ring[idx[k]], ring[idx[k + 1]]))
            break
    return tris


# ---------------------------------------------------------------------------
# 主积分：两个 TIN 曲面
# ---------------------------------------------------------------------------

@dataclass
class CellVolume:
    """可追溯的最小积分单元（前端可从汇总下钻到此）。"""
    cell_id: int
    ground_tri: int
    design_tri: int
    area: float
    cut: float
    fill: float
    mean_diff: float
    polygon: list[tuple[float, float]]


@dataclass
class VolumeReport:
    cut_volume: float
    fill_volume: float
    net_volume: float
    area_evaluated: float
    area_outside: float          # 共同覆盖区之外（缺测/边界缝隙），不积分不外推
    area_gap_note: str
    cells: list[CellVolume] = field(default_factory=list)
    method: str = "tin_exact"
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "method": self.method,
            "cut_volume_m3": round(float(self.cut_volume), 4),
            "fill_volume_m3": round(float(self.fill_volume), 4),
            "net_volume_m3": round(float(self.net_volume), 4),
            "gross_movement_m3": round(float(self.cut_volume + self.fill_volume), 4),
            "area_evaluated_m2": round(float(self.area_evaluated), 4),
            "area_not_evaluated_m2": round(float(self.area_outside), 4),
            "cell_count": len(self.cells),
            "warnings": self.warnings,
            "area_gap_note": self.area_gap_note,
        }


def _intersect_split_by_zeroline(
    inter: SPoly, f_g: Callable, f_d: Callable
) -> list[tuple[np.ndarray, np.ndarray]]:
    """交集多边形上用 diff=0 折线分割，返回 (三角顶点坐标, 三个 diff 值) 列表。

    若整个多边形同号则不必分割，直接耳切。
    """
    coords = np.array(inter.exterior.coords[:-1])
    diffs = np.array([f_g(x, y) - f_d(x, y) for x, y in coords])

    def clip_polygon(verts, vals, positive: bool):
        """Sutherland–Hodgman 用半平面 diff>=0 / <=0 裁剪。"""
        out_v, out_s = list(verts), list(vals)
        for edge_half in (True,):
            inv, ins = out_v, out_s
            out_v2, out_s2 = [], []
            n = len(inv)
            for k in range(n):
                x1, s1 = inv[k - 1], ins[k - 1]
                x2, s2 = inv[k], ins[k]
                in1 = (s1 >= 0) if positive else (s1 <= 0)
                in2 = (s2 >= 0) if positive else (s2 <= 0)
                if in2:
                    if not in1:
                        t = s1 / (s1 - s2) if (s1 - s2) != 0 else 0.0
                        xi = x1 + t * (x2 - x1)
                        out_v2.append(xi)
                        out_s2.append(0.0)
                    out_v2.append(x2)
                    out_s2.append(s2)
                elif in1:
                    t = s1 / (s1 - s2) if (s1 - s2) != 0 else 0.0
                    xi = x1 + t * (x2 - x1)
                    out_v2.append(xi)
                    out_s2.append(0.0)
            out_v, out_s = out_v2, out_s2
        return out_v, out_s

    result = []
    if np.all(diffs >= -1e-12) or np.all(diffs <= 1e-12):
        for tri in _ear_triangulate(inter):
            arr = np.array(tri)
            result.append((arr, np.array(
                [f_g(x, y) - f_d(x, y) for x, y in arr]
            )))
    else:
        for positive in (True, False):
            v, s = clip_polygon(coords, diffs, positive)
            if len(v) < 3:
                continue
            sub = SPoly(np.asarray(v))
            if sub.is_empty or sub.area <= 1e-12:
                continue
            # 裁剪结果一般为凸多边形（两凸三角片的交集被直线切），直接扇形
            varr = np.asarray(v)
            a = varr[0]
            for k in range(1, len(varr) - 1):
                tri = np.array([a, varr[k], varr[k + 1]])
                result.append((tri, np.array(
                    [f_g(x, y) - f_d(x, y) for x, y in tri]
                )))
    return result


def integrate_tin_vs_surface(
    ground: TINSurface,
    design,                       # TINSurface 或 design 模块对象（含 interpolate_triangle）
    domain: SPoly,
    design_kind: str = "tin",
) -> VolumeReport:
    """对两曲面对每个相交三角片对精确积分。

    design:
      - design_kind="tin": 另一个 TINSurface
      - design_kind="plane": 提供 .coeff (a,b,c) 的平面 z=ax+by+c
    """
    warnings: list[str] = []
    cells: list[CellVolume] = []

    g_polys = ground._polys
    if design_kind == "tin":
        d_polys = design._polys

    # 空间粗筛：先按 bbox 索引设计三角形
    if design_kind == "tin":
        from shapely.strtree import STRtree
        d_tree = STRtree(d_polys)

    total_area = cut_total = fill_total = 0.0
    cell_id = 0

    for gi, gtri_idx in enumerate(ground.r.triangles):
        gp = g_polys[gi]
        if not gp.intersects(domain):
            continue
        g3 = ground.r.points[gtri_idx]
        ga = _affine_on_triangle(g3)
        fg = lambda x, y, a=ga: a[0] * x + a[1] * y + a[2]

        candidates = []
        if design_kind == "plane":
            a, b, c = design.coeff
            candidates = [("plane", gp, lambda x, y, a=a, b=b, c=c: a * x + b * y + c)]
        else:
            for di in d_tree.query(gp):
                dp = d_polys[int(di)]
                inter = gp.intersection(dp)
                if inter.is_empty or inter.area <= 1e-12:
                    continue
                d3 = design.r.points[design.r.triangles[int(di)]]
                da = _affine_on_triangle(d3)
                if da is None:
                    continue
                candidates.append((int(di), inter,
                                   lambda x, y, a=da: a[0] * x + a[1] * y + a[2]))

        for di, inter, fd in candidates:
            inter = inter.intersection(domain)
            if inter.is_empty or inter.area <= 1e-9:
                continue
            geoms = getattr(inter, "geoms", [inter])
            for part in geoms:
                if part.geom_type != "Polygon" or part.area <= 1e-12:
                    continue
                for tri, dvals in _intersect_split_by_zeroline(part, fg, fd):
                    (x1, y1), (x2, y2), (x3, y3) = tri
                    area = 0.5 * abs(
                        x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2)
                    )
                    if area <= 1e-12:
                        continue
                    # ∫ max(diff,0) / max(-diff,0)：子三角由零线裁出，
                    # 同号；对仿射 diff 精确积分 = 面积 * 顶点均值
                    mean_d = float(np.mean(dvals))
                    if min(dvals) >= -1e-9:
                        cut_v = area * max(mean_d, 0.0)
                        fill_v = 0.0
                    elif max(dvals) <= 1e-9:
                        cut_v = 0.0
                        fill_v = area * max(-mean_d, 0.0)
                    else:
                        # 理论上零线裁剪后不会跨号；数值残余时按正/负角锥分开
                        pos = np.maximum(dvals, 0)
                        neg = np.maximum(-dvals, 0)
                        cut_v = area * pos.sum() / 3
                        fill_v = area * neg.sum() / 3
                    cut_total += cut_v
                    fill_total += fill_v
                    total_area += area
                    cells.append(CellVolume(
                        cell_id=cell_id,
                        ground_tri=gi,
                        design_tri=(-1 if di == "plane" else di),
                        area=area,
                        cut=cut_v,
                        fill=fill_v,
                        mean_diff=mean_d,
                        polygon=[tuple(p) for p in tri],
                    ))
                    cell_id += 1

    # 未评价面积：域内两张曲面未共同覆盖（外边界缝隙 + 内部缺测）
    gap = 0.0
    note = ""
    try:
        g_cov = unary_union(g_polys)
        if design_kind == "tin":
            common = g_cov.intersection(unary_union(d_polys))
        else:
            common = g_cov
        gap = domain.difference(common).area
        if gap > 1e-6:
            note = (
                f"有 {gap:.2f} m² 域内区域因边界内接缝隙或局部缺测未被两侧"
                "曲面共同覆盖，未计入体积，也未外推。"
            )
            warnings.append(note)
    except Exception as exc:  # pragma: no cover
        note = f"未覆盖面积计算失败: {exc}"

    return VolumeReport(
        cut_volume=cut_total,
        fill_volume=fill_total,
        net_volume=cut_total - fill_total,
        area_evaluated=total_area,
        area_outside=gap,
        area_gap_note=note,
        cells=cells,
    )


# ---------------------------------------------------------------------------
# 规则网格法（精度对比）：不外推，中心落在共同覆盖区内才计数
# ---------------------------------------------------------------------------

def integrate_grid(
    ground: TINSurface,
    design,
    domain: SPoly,
    spacing: float,
    design_kind: str = "tin",
) -> VolumeReport:
    """中点矩形法：在限定域内铺规则网格，逐格中点查询两张曲面。

    任一曲面在中点缺值（洞/缺测/边界外）则该格不计、也不补值。
    spacing 越小结果越趋近 TIN 精确积分，可用于网格精度影响比较。
    """
    minx, miny, maxx, maxy = domain.bounds
    nx = max(1, int(math.ceil((maxx - minx) / spacing)))
    ny = max(1, int(math.ceil((maxy - miny) / spacing)))
    cell_area = spacing * spacing

    if design_kind == "plane":
        a, b, c = design.coeff
        d_interp = lambda x, y: a * x + b * y + c
    else:
        d_interp = design.interpolate

    cut = fill = counted = 0.0
    covered_cells = 0
    for i in range(nx):
        for j in range(ny):
            x = minx + (i + 0.5) * spacing
            y = miny + (j + 0.5) * spacing
            if not domain.covers(Point(x, y)):
                continue
            zg = ground.interpolate(x, y)
            zd = d_interp(x, y)
            if zg is None or zd is None:
                continue  # 缺测格：不外推
            covered_cells += 1
            diff = zg - zd
            counted += cell_area
            if diff > 0:
                cut += diff * cell_area
            else:
                fill += -diff * cell_area

    note = (
        f"网格法 {spacing:g} m：共 {nx}×{ny} 候选格，"
        f"{covered_cells} 格双侧有值。格中心近似，边界处有 stair-step 误差。"
    )
    return VolumeReport(
        cut_volume=cut, fill_volume=fill, net_volume=cut - fill,
        area_evaluated=counted, area_outside=domain.area - counted,
        area_gap_note=note, method=f"grid_{spacing:g}m",
        warnings=[note],
    )
