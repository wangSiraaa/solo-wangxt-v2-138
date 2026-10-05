"""断面：沿指定折线（断面线）采样原地面与设计面，并计算断面挖填面积。

断面图与三维场景、体积汇总是同一套曲面：沿折线按固定步长在 TIN 上
线性插值，域外/孔洞/缺测处高程为 None（图上断线，不补值）。

断面挖填面积（m²）用梯形法分段累加：
    cut_area = ∫ max(g-d, 0) ds
    fill_area = ∫ max(d-g, 0) ds
两端按各自有效区间 [s_first, s_last] 截断，不外推。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from shapely.geometry import LineString, Point

from .design import PlaneDesign


@dataclass
class SectionResult:
    stations: list[float]
    ground_z: list          # None 表示该处缺测/域外
    design_z: list
    cut_area: float
    fill_area: float
    valid_range: tuple[float, float]
    warnings: list[str]


def sample_section(surface, design, design_kind: str,
                   line_coords: list[tuple[float, float]],
                   step: float = 1.0) -> SectionResult:
    line = LineString(line_coords)
    if len(line_coords) < 2:
        raise ValueError("断面线至少需要 2 个点")

    length = line.length
    n = max(2, int(math.ceil(length / step)) + 1)
    ss = np.linspace(0, length, n)

    stations, gz, dz = [], [], []
    missing_g = missing_d = 0
    for s in ss:
        pt = line.interpolate(float(s))
        x, y = pt.x, pt.y
        g = surface.interpolate(x, y)
        if design_kind == "plane":
            a, b, c = design.coeff
            d = a * x + b * y + c
        else:
            d = design.interpolate(x, y)
        stations.append(float(s))
        gz.append(None if g is None else round(g, 4))
        dz.append(None if d is None else round(d, 4))
        if g is None:
            missing_g += 1
        if d is None:
            missing_d += 1

    # 双侧有效区间
    valid = [s for s, g, d in zip(stations, gz, dz) if g is not None and d is not None]
    warnings = []
    if not valid:
        return SectionResult(stations, gz, dz, 0.0, 0.0, (0.0, 0.0),
                             ["断面线与两张曲面共同覆盖区无交点，未计算断面面积。"])
    s0, s1 = valid[0], valid[-1]
    if s0 > 1e-6 or s1 < length - 1e-6:
        warnings.append(
            f"断面在 [{s0:.2f}, {s1:.2f}] m（全线 {length:.2f} m）双侧有值，"
            "其余段落落在域外或缺测，已截断、未外推。"
        )

    cut_a = fill_a = 0.0
    prev = None
    for s, g, d in zip(stations, gz, dz):
        if g is None or d is None:
            prev = None  # 缺测断开，梯形不累加
            continue
        if prev is not None:
            ds = s - prev[0]
            dcut = max(prev[1] - prev[2], 0.0)
            dcut2 = max(g - d, 0.0)
            dfill = max(prev[2] - prev[1], 0.0)
            dfill2 = max(d - g, 0.0)
            cut_a += 0.5 * (dcut + dcut2) * ds
            fill_a += 0.5 * (dfill + dfill2) * ds
        prev = (s, g, d)

    if missing_g or missing_d:
        warnings.append(
            f"采样 {n} 点：原地面缺测 {missing_g} 点、设计面缺测 {missing_d} 点。"
        )

    return SectionResult(
        stations=[round(v, 4) for v in stations],
        ground_z=gz, design_z=dz,
        cut_area=cut_a, fill_area=fill_a,
        valid_range=(round(s0, 4), round(s1, 4)),
        warnings=warnings,
    )
