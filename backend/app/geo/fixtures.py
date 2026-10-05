"""内置软件算例（不替代现场计量认定）。

case_slope:  平面坡地，可完全手算校核
case_hole:   边界带孔洞
case_missing:局部缺测（点云中央空洞）
case_dirty:  重复点 / 高程冲突 / 边界外点 / 退化共线点
"""
from __future__ import annotations

import math


def case_slope() -> dict:
    """100×100 m 正方形，原地面 z_g = 0.02 x（东西向 2% 坡），
    设计面水平 z_d = 1.0。

    手算（理论值）：
      x=0   处 diff = -1.0（填），x=100 处 diff = +1.0（挖），零线 x=50。
      挖剖面（x∈[50,100]）是三角形：∫_50^100 (0.02x-1) dx
          = [0.01x² - x]_50^100 = (100-100) - (25-50) = 25 m²
      y 方向长度 100 m：
          V_cut = V_fill = 25 × 100 = 2500 m³，净体积 = 0。
      总搬运量 5000 m³ —— 若只报净值 0 就完全掩盖了挖填，这正是
      “挖填分别积分”要求的原因。
    """
    pts = [
        {"id": "g1", "x": 0, "y": 0, "z": 0.0},
        {"id": "g2", "x": 100, "y": 0, "z": 2.0},
        {"id": "g3", "x": 100, "y": 100, "z": 2.0},
        {"id": "g4", "x": 0, "y": 100, "z": 0.0},
    ]
    boundary = {
        "type": "Polygon",
        "coordinates": [[
            [0, 0], [100, 0], [100, 100], [0, 100], [0, 0]
        ]],
    }
    return {
        "name": "平面坡地（可手算）",
        "expected": {
            "cut_volume_m3": 2500.0,
            "fill_volume_m3": 2500.0,
            "net_volume_m3": 0.0,
            "gross_movement_m3": 5000.0,
            "area_m2": 10000.0,
        },
        "payload": {
            "target_epsg": 32650,
            "target_vertical_datum": "local",
            "boundary": boundary,
            "ground": {"epsg": 32650, "vertical_datum": "local", "points": pts},
            "design": {"kind": "plane", "a": 0.0, "b": 0.0, "c": 1.0},
            "grid_spacings": [20, 10, 5, 2],
            "sections": [
                {"name": "中线纵断面 y=50", "line": [[0, 50], [100, 50]], "step": 2.0},
                {"name": "南端纵断面 y=5", "line": [[0, 5], [100, 5]], "step": 2.0},
            ],
        },
    }


def case_hole() -> dict:
    """100×100 场地中央有 20×20 既有构筑物（孔洞，明确不计量）。

    原地面仍是 z=0.02x 的平面坡，设计 z=1.0。孔洞沿 x 方向占据
    [40,60]，在该条带内挖填零线区域被扣除：
      孔洞切掉的挖方 = 挖剖面在 x∈[50,60] 的面积 × 20
          ∫_50^60 (0.02x-1) dx = [0.01x²-x]_50^60
          = (36-60)-(25-50) = -24-(-25) = 1 m² → 20 m³
      孔洞切掉的填方 = x∈[40,50]:
          ∫_40^50 (1-0.02x) dx = [x-0.01x²]_40^50
          = (50-25)-(40-16) = 25-24 = 1 m² → 20 m³
      => V_cut = V_fill = 2500 - 20 = 2480 m³，域面积 = 10000-400 = 9600 m²。
    """
    pts = [
        {"id": "g1", "x": 0, "y": 0, "z": 0.0},
        {"id": "g2", "x": 100, "y": 0, "z": 2.0},
        {"id": "g3", "x": 100, "y": 100, "z": 2.0},
        {"id": "g4", "x": 0, "y": 100, "z": 0.0},
    ]
    boundary = {
        "type": "Polygon",
        "coordinates": [
            [[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]],
            # 孔洞（内环）
            [[40, 40], [40, 60], [60, 60], [60, 40], [40, 40]],
        ],
    }
    return {
        "name": "边界孔洞（中央既有构筑物）",
        "expected": {
            "cut_volume_m3": 2480.0,
            "fill_volume_m3": 2480.0,
            "net_volume_m3": 0.0,
            "area_m2": 9600.0,
        },
        "payload": {
            "target_epsg": 32650,
            "target_vertical_datum": "local",
            "boundary": boundary,
            "ground": {"epsg": 32650, "vertical_datum": "local", "points": pts},
            "design": {"kind": "plane", "a": 0.0, "b": 0.0, "c": 1.0},
            "grid_spacings": [10, 5],
            "sections": [
                {"name": "穿过孔洞 y=50", "line": [[0, 50], [100, 50]], "step": 2.0},
            ],
        },
    }


def case_missing() -> dict:
    """100×100 场地，10 m 规则网格测量，但中央 40×40 区域缺测。

    缺失范围 x∈(30,70), y∈(30,70)（边界上的点保留），名义 1600 m²。
    该区域被四周密集点包围，系统应：
      - 拒绝跨越该区域的长条/扁圆三角片（边长/外接圆超限，α-shape），
      - 报告 interior_gap_area ≈ 1400 m²，不计体积、不外推，断面断线；
      - 缺测矩形 4 个角上各有 1 个由 3 个实测点围成的半格三角片
        （30,30)-(40,30)-(30,40) 等，共 200 m²），其三顶点均实测、
        外接圆与正常半格无异（R≈7.07），属合法线性内插，予以保留——
        这 200 m² 与中间 1400 m² 的区分正是算法严谨性的体现：
        有三个实测顶点支撑才内插，其余一律不外推。
    """
    pts = []
    k = 0
    for i in range(0, 101, 10):
        for j in range(0, 101, 10):
            if 30 < i < 70 and 30 < j < 70:
                continue  # 模拟局部缺测
            pts.append({"id": f"s{k}", "x": float(i), "y": float(j),
                        "z": 0.02 * i})
            k += 1
    boundary = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]]],
    }
    return {
        "name": "局部缺测（中央无测点）",
        "expected_note": (
            "中央约 40×40 m 未评价：系统必须报告 interior_gap_area>0，"
            "体积仅在周边有数据区域积分，且不得补点外推。"
        ),
        "payload": {
            "target_epsg": 32650,
            "target_vertical_datum": "local",
            "boundary": boundary,
            "ground": {"epsg": 32650, "vertical_datum": "local", "points": pts},
            "design": {"kind": "plane", "a": 0.0, "b": 0.0, "c": 1.0},
            "grid_spacings": [10, 5],
            "sections": [
                {"name": "中线纵断面（中央应断线）",
                 "line": [[0, 50], [100, 50]], "step": 2.0},
            ],
        },
    }


def case_dirty() -> dict:
    """脏数据：完全重复点、同平面高程冲突、边界外点、共线退化点。"""
    pts = [
        {"id": "p1", "x": 0, "y": 0, "z": 0.0},
        {"id": "p2", "x": 100, "y": 0, "z": 2.0},
        {"id": "p3", "x": 100, "y": 100, "z": 2.0},
        {"id": "p4", "x": 0, "y": 100, "z": 0.0},
        {"id": "p1_dup", "x": 0, "y": 0, "z": 0.0},              # 完全重复
        {"id": "p3_conflict", "x": 100, "y": 100, "z": 2.35},    # 高程冲突
        {"id": "p_out", "x": 130, "y": 50, "z": 5.0},            # 边界外
        {"id": "p_collinear", "x": 50, "y": 0, "z": 1.0},        # 边上共线（合法点，不退化）
        {"id": "p_bad", "x": 20, "y": 20, "z": float("nan")},    # 非法值
    ]
    boundary = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]]],
    }
    return {
        "name": "脏数据（重复/冲突/越界/非法值）",
        "expected_note": (
            "问题清单应包含 1 个完全重复点、1 组高程冲突（p3 2.0 vs 2.35，"
            "取均值 2.175 并要求复核）、1 个边界外点、1 个 NaN 点；"
            "所有问题逐项列出，不静默丢弃。"
        ),
        "payload": {
            "target_epsg": 32650,
            "target_vertical_datum": "local",
            "boundary": boundary,
            "ground": {"epsg": 32650, "vertical_datum": "local", "points": pts},
            "design": {"kind": "plane", "a": 0.0, "b": 0.0, "c": 1.0},
            "grid_spacings": [10],
            "sections": [],
        },
    }


ALL_CASES = {
    "slope": case_slope,
    "hole": case_hole,
    "missing": case_missing,
    "dirty": case_dirty,
}
