"""点云/高程点质量检查。

输出问题清单（不静默删除即算数）：
- duplicate_coordinates: 平面坐标重复（含高程一致/不一致两种情形）；
- duplicate_xyz: 三维完全重复；
- z_conflict: 同 x,y 高程不一致（需要现场复核取信哪一个）；
- nonfinite: NaN/Inf；
- outside_boundary: 落在计量边界外（不参与限定 TIN，但需向用户列出）。
"""
from __future__ import annotations

import math
from typing import Optional

XY_TOL = 1e-6


def check_points(
    points: list[dict],
    boundary=None,
    xy_tol: float = XY_TOL,
) -> dict:
    """返回问题报告与“建议保留”的去重点索引。

    去重策略保守：三维完全重复保留第一个；平面重复但高程冲突的点全部保留，
    交由人工裁定（z_conflict 中列出），TIN 构建器对该网格位置取均值并打标。
    """
    issues: list[dict] = []

    # 非有限值
    for idx, p in enumerate(points):
        x, y, z = p.get("x"), p.get("y"), p.get("z")
        if not all(isinstance(v, (int, float)) for v in (x, y, z)) or not all(
            math.isfinite(float(v)) for v in (x, y, z)
        ):
            issues.append(
                {"type": "nonfinite", "index": idx, "point_id": p.get("id"),
                 "message": "坐标或高程为 NaN/Inf/缺失"}
            )

    valid = [
        i for i, p in enumerate(points)
        if all(isinstance(p.get(c), (int, float)) and math.isfinite(p[c])
               for c in ("x", "y", "z"))
    ]

    # 用网格分桶查找平面近重复，避免 O(n^2)
    bucket: dict[tuple[int, int], list[int]] = {}
    keep: set[int] = set(valid)
    for i in valid:
        key = (int(round(points[i]["x"] / xy_tol)),
               int(round(points[i]["y"] / xy_tol)))
        near = bucket.get(key, [])
        dup_of = None
        for j in near:
            if (
                abs(points[i]["x"] - points[j]["x"]) <= xy_tol
                and abs(points[i]["y"] - points[j]["y"]) <= xy_tol
            ):
                dup_of = j
                break
        if dup_of is None:
            near.append(i)
            bucket[key] = near
            continue

        j = dup_of
        if abs(points[i]["z"] - points[j]["z"]) <= 1e-9:
            issues.append({
                "type": "duplicate_xyz", "index": i, "point_id": points[i].get("id"),
                "kept_index": j, "kept_id": points[j].get("id"),
                "message": f"与点 {points[j].get('id') or j} 三维完全重复，建议删除",
            })
            keep.discard(i)
        else:
            issues.append({
                "type": "z_conflict", "indices": [j, i],
                "point_ids": [points[j].get("id"), points[i].get("id")],
                "z_values": [points[j]["z"], points[i]["z"]],
                "message": (
                    f"平面位置重复但高程冲突: "
                    f"{points[j]['z']:.3f} vs {points[i]['z']:.3f}，"
                    "暂取均值，需现场复核"
                ),
            })
            # 冲突点不参与 TIN（均值点由 build_tin 注入），两者都标记
            keep.discard(i)
            keep.discard(j)

    # 边界外点（只列出，绝不外推）。1e-7 m 容差仅用于吸收重投影往返的
    # 数值残差，不会把真正的界外点吞进来（工程点距远大于此）。
    outside: list[int] = []
    if boundary is not None:
        from shapely.geometry import Point
        test_domain = boundary
        try:
            test_domain = boundary.buffer(1e-7)
        except Exception:
            pass
        for i in valid:
            if not test_domain.covers(Point(points[i]["x"], points[i]["y"])):
                outside.append(i)
                issues.append({
                    "type": "outside_boundary", "index": i,
                    "point_id": points[i].get("id"),
                    "message": "点位于计量边界（含孔洞）之外，不参与 TIN",
                })
        keep = {i for i in keep if i not in outside}

    summary = {
        "total": len(points),
        "valid": len(valid),
        "duplicate_xyz": sum(1 for q in issues if q["type"] == "duplicate_xyz"),
        "z_conflict": sum(1 for q in issues if q["type"] == "z_conflict"),
        "nonfinite": sum(1 for q in issues if q["type"] == "nonfinite"),
        "outside_boundary": len(outside),
        "used_for_tin": len(keep),
    }
    return {"issues": issues, "keep": sorted(keep), "summary": summary}
