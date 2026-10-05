"""数据质量检查——问题必须显式列出，不能静默处理。

检查项：
  1. 重复点：平面坐标完全一致 -> 列出；高程不一致判为 error（数据矛盾）；
  2. 三角网退化：面积≈0 或质量 2r/R 极低；
  3. 边界外点：点不在声明的边界多边形内；
  4. 基准不一致：原地面与设计面的平面坐标 / 高程基准不一致 -> error；
  5. 疑似缺测片：地图片面积很大且质量差（Delaunay 跨过大空区）。
"""
from __future__ import annotations

import numpy as np
from shapely.geometry import Point as ShPoint

from .models import QCIssue


def _duplicate_issues(points, surface: str, tol: float = 1e-6) -> list[QCIssue]:
    issues: list[QCIssue] = []
    seen: dict[tuple[int, int], list[int]] = {}
    # 按 1e-3 m 网格分桶（mm 级容差）
    for idx, p in enumerate(points):
        key = (round(p.x / tol), round(p.y / tol))
        seen.setdefault(key, []).append(idx)
    for key, idxs in seen.items():
        if len(idxs) < 2:
            continue
        zs = [points[i].z for i in idxs]
        x, y = points[idxs[0]].x, points[idxs[0]].y
        if max(zs) - min(zs) > 1e-3:
            issues.append(QCIssue(
                kind="duplicate_conflict", severity="error",
                message=(f"{surface}: {len(idxs)} 个点平面坐标重合但高程不一致"
                         f"（{min(zs):.3f}~{max(zs):.3f} m），数据矛盾需现场复核"),
                coords=[(points[i].x, points[i].y) for i in idxs],
                values={"zs": zs, "indices": idxs}))
        else:
            issues.append(QCIssue(
                kind="duplicate_exact", severity="warning",
                message=f"{surface}: {len(idxs)} 个重复点（坐标高程一致），建模时自动去重",
                coords=[(x, y)],
                values={"indices": idxs}))
    return issues


def _outside_issues(points, region, surface: str) -> list[QCIssue]:
    issues = []
    grown = region.buffer(1e-6) if region is not None else None
    for p in points:
        if grown is not None and not grown.covers(ShPoint(p.x, p.y)):
            issues.append(QCIssue(
                kind="outside", severity="warning",
                message=f"{surface}: 点 ({p.x:.2f},{p.y:.2f},z={p.z:.2f}) 在边界外，"
                        f"不参与计算也不外推",
                coords=[(p.x, p.y)]))
    return issues


def _degenerate_issues(tin, surface: str) -> list[QCIssue]:
    issues = []
    for verts, area, quality in tin.degenerate:
        coords = [tuple(tin.coords[i]) for i in verts]
        issues.append(QCIssue(
            kind="degenerate", severity="warning",
            message=(f"{surface}: 三角片 {verts} 退化"
                     f"（面积 {area:.2e} m²，质量 {quality:.4f}），已跳过"),
            triangle=coords,
            values={"area": area, "quality": quality}))
    return issues


def _oversized_issues(tin, surface: str,
                      max_area: float, min_quality: float) -> list[QCIssue]:
    """大面积瘦长三角片往往意味着点云空区（缺测被 Delaunay 跨过）。

    在完整 Delaunay 剖分上检查（空区在点集凸包内部，仅看边界裁剪片会漏检）。
    """
    issues = []
    seen = set()
    for t in range(len(tin.tri.simplices)):
        verts = tin.tri.simplices[t]
        pts3 = tin.coords[verts]
        from .geometry import tri_quality
        area, quality = tri_quality(pts3[0], pts3[1], pts3[2])
        if area > max_area and quality < 0.25:
            key = tuple(int(x) for x in verts)
            if key in seen:
                continue
            seen.add(key)
            issues.append(QCIssue(
                kind="oversized", severity="warning",
                message=(f"{surface}: 三角片面积 {area:.1f} m² 且形状瘦长"
                         f"（质量 {quality:.3f}），疑似存在局部缺测空区，"
                         f"应补测或显式圈出缺测范围，不得默认按网面计量"),
                triangle=[tuple(tin.coords[i]) for i in verts],
                values={"area": float(area), "quality": float(quality)}))
    return issues


def run_qc(ground_pts, design_pts, ground_tin, design_tin,
           datum, design_datum,
           gap_max_area, gap_min_quality) -> list[QCIssue]:
    issues: list[QCIssue] = []
    issues += _duplicate_issues(ground_pts, "原地面")
    issues += _duplicate_issues(design_pts, "设计面")
    issues += _outside_issues(ground_pts, ground_tin.region, "原地面")
    issues += _outside_issues(design_pts, design_tin.region, "设计面")
    issues += _degenerate_issues(ground_tin, "原地面")
    issues += _degenerate_issues(design_tin, "设计面")
    issues += _oversized_issues(ground_tin, "原地面", gap_max_area, gap_min_quality)
    issues += _oversized_issues(design_tin, "设计面", gap_max_area, gap_min_quality)

    if design_datum is not None:
        if (design_datum.horizontal_crs and datum.horizontal_crs
                and design_datum.horizontal_crs != datum.horizontal_crs):
            issues.append(QCIssue(
                kind="datum", severity="error",
                message=(f"平面坐标系不一致：原地面 {datum.horizontal_crs} vs "
                         f"设计面 {design_datum.horizontal_crs}，必须先转换统一"),
                values={"ground_crs": datum.horizontal_crs,
                        "design_crs": design_datum.horizontal_crs}))
        if (design_datum.vertical_datum and datum.vertical_datum
                and design_datum.vertical_datum != datum.vertical_datum):
            issues.append(QCIssue(
                kind="datum", severity="error",
                message=(f"高程基准不一致：原地面 {datum.vertical_datum} vs "
                         f"设计面 {design_datum.vertical_datum}，必须先拟合/水准联测统一"),
                values={"ground_vd": datum.vertical_datum,
                        "design_vd": design_datum.vertical_datum}))
    return issues
