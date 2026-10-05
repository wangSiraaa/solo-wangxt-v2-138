"""规则网格（角点法 / 棱柱法）计算挖填，用于与 TIN 精确积分结果比较。

关键原则与 TIN 一致：网格角点落在任一面 TIN 凸包外时，该单元不参与
计算（不内插假设、不外推）。
"""
from __future__ import annotations

import numpy as np
from shapely.geometry import Point as ShPoint, box

from .models import GridResult


def grid_volume(ground_tin, design_tin, size: float,
                method: str = "corner") -> GridResult:
    minx, miny, maxx, maxy = ground_tin.region.intersection(
        design_tin.region).bounds
    xs = np.arange(minx, maxx + 1e-9, size)
    ys = np.arange(miny, maxy + 1e-9, size)
    if len(xs) < 2 or len(ys) < 2:
        return GridResult(size=size, method=method, cut=0, fill=0, net=0,
                          area=0, n_cells=0, n_cells_used=0,
                          diff_cut_vs_tin=0, diff_fill_vs_tin=0,
                          rel_cut_pct=0, rel_fill_pct=0)

    common = ground_tin.region.intersection(design_tin.region)

    # 角点高程（None=任一面缺数据）
    Zg = np.full((len(ys), len(xs)), np.nan)
    Zd = np.full((len(ys), len(xs)), np.nan)
    for i, y in enumerate(ys):
        for j, x in enumerate(xs):
            pt = ShPoint(x, y)
            if not common.covers(pt):
                continue
            zg = ground_tin.z_at(x, y)
            zd = design_tin.z_at(x, y)
            if zg is not None and zd is not None:
                Zg[i, j] = zg
                Zd[i, j] = zd

    cell_area = size * size
    cut = fill = area = 0.0
    n_total = n_used = 0
    for i in range(len(ys) - 1):
        for j in range(len(xs) - 1):
            n_total += 1
            zg = Zg[i:i + 2, j:j + 2].ravel()
            zd = Zd[i:i + 2, j:j + 2].ravel()
            if np.any(np.isnan(zg)) or np.any(np.isnan(zd)):
                continue
            # 单元中心须在公共区域内，防止凹边界处四角落入但中心在外
            cx = (xs[j] + xs[j + 1]) / 2
            cy = (ys[i] + ys[i + 1]) / 2
            if not common.covers(ShPoint(cx, cy)):
                continue
            dz = zg - zd
            n_used += 1
            area += cell_area
            # 角点法：挖、填分别取各角点挖深/填高之和乘面积/4
            # （跨零单元在角点法中近似拆开；精确跨零拆分以 TIN 积分结果为准）
            cut += float(np.maximum(dz, 0).sum()) * cell_area / 4.0
            fill += float(np.maximum(-dz, 0).sum()) * cell_area / 4.0

    return GridResult(
        size=float(size), method=method,
        cut=float(cut), fill=float(fill), net=float(cut - fill),
        area=float(area), n_cells=n_total, n_cells_used=n_used,
        diff_cut_vs_tin=0, diff_fill_vs_tin=0,
        rel_cut_pct=0, rel_fill_pct=0,
    )


def compare_grids(ground_tin, design_tin, sizes=(10, 20, 25, 40),
                  tin_cut: float = 0, tin_fill: float = 0):
    """多档网格精度对比，附与 TIN 的相对偏差。"""
    results = []
    for s in sizes:
        r = grid_volume(ground_tin, design_tin, s)
        r.diff_cut_vs_tin = r.cut - tin_cut
        r.diff_fill_vs_tin = r.fill - tin_fill
        r.rel_cut_pct = (100 * r.diff_cut_vs_tin / tin_cut) if tin_cut else 0
        r.rel_fill_pct = (100 * r.diff_fill_vs_tin / tin_fill) if tin_fill else 0
        results.append(r)
    return results
