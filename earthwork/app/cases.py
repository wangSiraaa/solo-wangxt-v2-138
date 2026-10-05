"""内置软件算例。

case_plane  平面坡地可手算案例（无孔洞，严格校验算法）：
            100m x 100m 场地。原地面 zg=0.05x，设计面 zd=0.05y。
            零线 x=y，挖填对称：
            cut=fill=0.05 * ∫₀¹⁰⁰∫₀ˣ(x-y)dy dx
                     = 0.05 * 100³/6 = 8333.333 m³，净量=0。
case_hole   边界孔洞：场地中央 20x10 矩形洞（建构筑物/水塘不计量），
            洞跨零线，挖方扣 0.05·(20³-10³)/6=58.333、
            填方扣 0.05·10³/6=8.333（均可手算），
            期望 cut=8275.00, fill=8325.00，洞面积 200。
case_gap    局部缺测：挖掉填区一片原地面测点（矩形30-50 x 30-60），
            缺测区以 no_data 显式圈出，洞内不计算、不外推：
            挖方扣 0.05·20³/6=66.667，填方扣 66.667+150=216.667，
            期望 cut=8266.67, fill=8116.67，参与面积 9400。
case_rolling 起伏地形：用于三维展示与多档网格精度对比（无手算值）。
case_qc     数据质量案例：重复点、高程矛盾点、边界外点。
"""
from __future__ import annotations

import numpy as np

from .models import Datum, Point, Project, Ring

DATUM = Datum(horizontal_crs="EPSG:4547",
              vertical_datum="1985国家高程基准", units="m")


def _grid_points(x0, x1, y0, y1, step, zfunc, surface, skip=None):
    pts = []
    for x in np.arange(x0, x1 + 1e-9, step):
        for y in np.arange(y0, y1 + 1e-9, step):
            if skip and skip(x, y):
                continue
            pts.append(Point(x=float(x), y=float(y),
                             z=float(zfunc(x, y)), surface=surface))
    return pts


def case_plane() -> Project:
    g = _grid_points(0, 100, 0, 100, 25,
                     lambda x, y: 0.05 * x, "ground")
    d = _grid_points(0, 100, 0, 100, 25,
                     lambda x, y: 0.05 * y, "design")
    return Project(name="平面坡地可手算案例（零线x=y，cut=fill=8333.33m³）",
                   points=g + d, datum=DATUM)


def case_hole() -> Project:
    g = _grid_points(0, 100, 0, 100, 25,
                     lambda x, y: 0.05 * x, "ground")
    d = _grid_points(0, 100, 0, 100, 25,
                     lambda x, y: 0.05 * y, "design")
    hole = [(30, 30), (50, 30), (50, 40), (30, 40)]
    return Project(name="边界孔洞案例（中央20x10洞，cut=8275 fill=8325）",
                   points=g + d, holes=[hole], datum=DATUM)


def case_gap() -> Project:
    # 缺测矩形 30<=x<=50, 30<=y<=60 位于填区(x<y)，面积 20*30=600
    def skip(x, y):
        return 30 <= x <= 50 and 30 <= y <= 60

    g = _grid_points(0, 100, 0, 100, 10,
                     lambda x, y: 0.05 * x, "ground", skip=skip)
    d = _grid_points(0, 100, 0, 100, 25,
                     lambda x, y: 0.05 * y, "design")
    no_data = [[(30, 30), (50, 30), (50, 60), (30, 60)]]
    return Project(name="局部缺测案例（填区缺测600m²，cut=8266.67 fill=8116.67）",
                   points=g + d, no_data=no_data, datum=DATUM)


def case_rolling() -> Project:
    def zg(x, y):
        return 2.5 + 1.2 * np.sin(x / 20) + 0.8 * np.cos(y / 25) + 0.01 * x

    def zd(x, y):
        return 2.0 + 0.6 * np.sin((x + y) / 30) + 0.01 * x

    g = _grid_points(0, 100, 0, 100, 10, zg, "ground")
    d = _grid_points(0, 100, 0, 100, 20, zd, "design")
    return Project(name="起伏地形案例（三维展示/网格精度对比）",
                   points=g + d, datum=DATUM)


def case_qc() -> Project:
    g = _grid_points(0, 100, 0, 100, 25,
                     lambda x, y: 0.05 * x, "ground")
    d = _grid_points(0, 100, 0, 100, 25,
                     lambda x, y: 0.05 * y, "design")
    # 精确重复点
    g.append(Point(x=25, y=25, z=1.25, surface="ground", code="DUP"))
    # 同点高程矛盾
    g.append(Point(x=50, y=50, z=9.99, surface="ground", code="CONFLICT"))
    # 边界外点
    g.append(Point(x=130, y=50, z=6.5, surface="ground", code="OUTSIDE"))
    boundary = [Ring(coords=[(0, 0), (100, 0), (100, 100), (0, 100)])]
    return Project(name="数据质量检查案例（重复/矛盾/边界外）",
                   points=g + d, boundary=boundary, datum=DATUM)


ALL_CASES = {
    "plane": case_plane,
    "hole": case_hole,
    "gap": case_gap,
    "rolling": case_rolling,
    "qc": case_qc,
}
