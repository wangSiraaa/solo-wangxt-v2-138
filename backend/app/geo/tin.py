"""限定边界内的 TIN 构建与线性插值（SciPy Delaunay + Shapely 裁剪）。

核心纪律：边界外不擅自外推。

实现方式：对全部有效点做 Delaunay，然后逐三角形判定——只有“质心在边界内、
且三条边不穿越孔洞/边界”的三角形才保留。采用“质心 + 边不越界”的双重条件，
而不是简单判断三个顶点都在域内（凸三角形顶点在域外也可能覆盖域内区域；
反之顶点在域内的三角形在凹边界处也可能跨出去）。

域内未被任何保留三角形覆盖的区域（边界附近的窄条、点云内部的局部缺测洞）
会被显式计算并在报告中区分，绝不补点外推。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from scipy.spatial import Delaunay
from shapely.geometry import Polygon as ShapelyPolygon
from shapely.geometry import MultiPolygon
from shapely.geometry import mapping, shape
from shapely.ops import unary_union
from shapely.prepared import prep
from shapely.strtree import STRtree


@dataclass
class TINResult:
    triangles: list[list[int]]      # 每个三角形使用的“输入点”索引
    points: np.ndarray              # 实际参与构网的点 (m,3)
    point_ids: list                # 与 points 对齐的业务 id
    source_indices: list[int]       # points 行 -> 原始点列表索引
    injected_flags: list[bool]      # 该行是否为注入点（约束点/均值点）
    degraded: list[dict]            # 退化/低质量三角形（仍剔除后报告）
    rejected: list[dict]            # 被边界条件拒绝的三角形统计
    boundary_notes: list[str]       # 约束点注入/无法赋值说明
    uncovered_geom: object           # 域内未覆盖区域（Shapely）
    boundary_gap_area: float        # 沿外边界的未覆盖面积（内接 TIN 与边界之差）
    interior_gap_area: float        # 域内部缺测/孔洞旁的未覆盖面积
    covered_area: float
    domain_area: float
    hull_area: float


def _triangle_quality(pts: np.ndarray) -> dict:
    """返回面积、最小角（度）、最长边；退化三角形面积≈0。"""
    (x1, y1), (x2, y2), (x3, y3) = pts
    area = 0.5 * abs(
        x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2)
    )
    ang = []
    for i in range(3):
        ax, ay = pts[(i + 1) % 3] - pts[i]
        bx, by = pts[(i + 2) % 3] - pts[i]
        la = math.hypot(ax, ay)
        lb = math.hypot(bx, by)
        if la == 0 or lb == 0:
            ang.append(0.0)
            continue
        c = max(-1.0, min(1.0, (ax * bx + ay * by) / (la * lb)))
        ang.append(math.degrees(math.acos(c)))
    return {"area": area, "min_angle": min(ang), "max_edge": max(
        math.hypot(*(pts[1] - pts[0])),
        math.hypot(*(pts[2] - pts[1])),
        math.hypot(*(pts[0] - pts[2])),
    )}


def _circumradius(pts: np.ndarray, area: float) -> float:
    """R = abc / (4A)。α-shape 判据：外接圆过大说明该片跨越数据空洞。"""
    if area <= 1e-15:
        return float("inf")
    e = [
        math.hypot(*(pts[1] - pts[0])),
        math.hypot(*(pts[2] - pts[1])),
        math.hypot(*(pts[0] - pts[2])),
    ]
    return e[0] * e[1] * e[2] / (4.0 * area)


def _boundary_ring_points(
    domain: "ShapelyPolygon | MultiPolygon",
    densify_distance: Optional[float] = None,
) -> list[tuple[float, float]]:
    """收集外环 + 全部孔洞环的顶点；可选沿边按 densify_distance 加密。"""
    polys = list(domain.geoms) if domain.geom_type == "MultiPolygon" else [domain]
    out: list[tuple[float, float]] = []
    for poly in polys:
        rings = [poly.exterior, *poly.interiors]
        for ring in rings:
            coords = list(ring.coords)[:-1]  # 去闭合点
            if densify_distance and densify_distance > 0:
                densified: list[tuple[float, float]] = []
                for k in range(len(coords)):
                    a = coords[k]
                    b = coords[(k + 1) % len(coords)]
                    seg = math.hypot(b[0] - a[0], b[1] - a[1])
                    steps = max(1, int(math.ceil(seg / densify_distance)))
                    for t in range(steps):
                        frac = t / steps
                        densified.append(
                            (a[0] + frac * (b[0] - a[0]),
                             a[1] + frac * (b[1] - a[1]))
                        )
                coords = densified
            out.extend((float(x), float(y)) for x, y in coords)
    return out


def build_constrained_tin(
    points: list[dict],
    domain: "ShapelyPolygon | MultiPolygon",
    keep_indices: Optional[list[int]] = None,
    min_area: float = 1e-6,
    min_angle_deg: float = 1.0,
    densify_distance: Optional[float] = None,
    max_triangle_edge: Optional[float] = None,
    max_edge_factor: float = 3.5,
    max_circumradius: Optional[float] = None,
    max_circumradius_factor: float = 1.5,
) -> TINResult:
    """构建限定域 TIN（带边界约束点的 Delaunay + Shapely 裁剪）。

    约束点注入：外边界与孔洞环顶点作为 Steiner 点参与 Delaunay，使三角网
    沿环边贴合孔洞/凹边界；其高程在实测点凸包内用重心坐标线性内插得到
    （内插，不是外推），并以 __boundary__ 前缀显式标注。落在实测点凸包
    之外的环点无法赋值——不注入，对应位置留作 boundary_gap 报告。
    其余跨边界三角形一律拒绝（质心 + 三角形⊆域双重条件）。

    points: 原始点列表 [{"id","x","y","z"}]
    keep_indices: 质检后建议使用的索引；z 冲突点不在其中。
    densify_distance: 给定时按该间距加密环边（凹曲线边界更贴合）。
    """
    if keep_indices is None:
        keep_indices = list(range(len(points)))
    keep_set = set(keep_indices)

    # ---- z 冲突位置注入均值点（quality 已把冲突双方都排除出 keep） ----
    injected: list[dict] = []
    used_rows: list[int] = list(keep_indices)
    seen_xy: dict[tuple[int, int], int] = {}
    for i in keep_indices:
        key = (round(points[i]["x"] / 1e-6), round(points[i]["y"] / 1e-6))
        seen_xy[key] = i
    groups: dict[tuple[float, float], list[int]] = {}
    for i, p in enumerate(points):
        if i in keep_set:
            continue
        if not all(isinstance(p.get(c), (int, float)) for c in ("x", "y", "z")):
            continue
        groups.setdefault((p["x"], p["y"]), []).append(i)
    for (x, y), idxs in groups.items():
        also_keep = [seen_xy[(round(x / 1e-6), round(y / 1e-6))]] \
            if (round(x / 1e-6), round(y / 1e-6)) in seen_xy else []
        allidx = idxs + also_keep
        zs = [points[i]["z"] for i in allidx if math.isfinite(points[i]["z"])]
        if len(set(round(z, 9) for z in zs)) <= 1:
            continue
        injected.append({
            "id": f"__mean_{len(injected)}",
            "x": x, "y": y,
            "z": float(np.mean(zs)),
            "_injected": True,
            "_source_ids": [points[i].get("id") for i in allidx],
        })
        for i in also_keep:
            used_rows.remove(i)

    measured = [points[i] for i in used_rows]
    if len(measured) < 3:
        raise ValueError("边界内有效点不足 3 个，无法构建 TIN；请补充测量点。")

    m_xy = np.array([[p["x"], p["y"]] for p in measured], dtype=float)
    m_z = np.array([p["z"] for p in measured], dtype=float)

    # ---- 边界约束点：凸包内插赋值 ----
    boundary_notes: list[str] = []
    boundary_pts = _boundary_ring_points(domain, densify_distance)
    base_delaunay = Delaunay(m_xy, qhull_options="Qbb Qc Qz Q12")

    def measured_z_at(x: float, y: float) -> Optional[float]:
        simp = base_delaunay.find_simplex(np.array([[x, y]]))
        if simp[0] < 0:
            return None  # 凸包外：不外推
        t = base_delaunay.simplices[simp[0]]
        lam = _barycentric(np.array([x, y]), m_xy[t])
        if lam is None:
            return None
        return float(lam @ m_z[t])

    for bi, (x, y) in enumerate(boundary_pts):
        # 与已有实测点/注入点重合则跳过
        if any(abs(x - p["x"]) <= 1e-6 and abs(y - p["y"]) <= 1e-6
               for p in measured + injected):
            continue
        z = measured_z_at(x, y)
        if z is None:
            boundary_notes.append(
                f"边界点 ({x:.2f},{y:.2f}) 位于实测点凸包之外，无法内插"
                "高程，未注入；该处将计入边界未覆盖面积。"
            )
            continue
        injected.append({
            "id": f"__boundary_{bi}", "x": x, "y": y, "z": z,
            "_injected": True, "_boundary_constraint": True,
        })
    if any(p.get("_boundary_constraint") for p in injected):
        n_b = sum(1 for p in injected if p.get("_boundary_constraint"))
        boundary_notes.insert(0, (
            f"注入 {n_b} 个边界/孔洞约束点，其高程为实测点凸包内线性内插值"
            "（非实测、非外推），用于让 TIN 贴合边界与孔洞。"
        ))

    all_pts = measured + injected
    xy = np.array([[p["x"], p["y"]] for p in all_pts], dtype=float)
    z = np.array([p["z"] for p in all_pts], dtype=float)
    point_ids = [p.get("id") for p in all_pts]
    source_indices = used_rows + [-1] * len(injected)
    injected_flags = [False] * len(measured) + [bool(p.get("_injected")) for p in injected]

    tri = Delaunay(xy, qhull_options="Qbb Qc Qz Q12")

    # 缺测区防护阈值：防止长条/扁圆三角形把无数据处“连起来”（等同外推）。
    #   1) 最大边长；2) 最大外接圆半径（α-shape 判据，更能剔除贴洞边的
    #      扁三角——边长可能不大，但外接圆明显偏大）。
    # 基准尺度取实测点最近邻间距中位数。
    typical = 0.0
    if len(m_xy) > 1:
        from scipy.spatial import cKDTree
        sample = m_xy if len(m_xy) <= 5000 else m_xy[
            np.linspace(0, len(m_xy) - 1, 5000).astype(int)]
        d2, _ = cKDTree(m_xy).query(sample, k=2)
        nn = d2[:, 1]
        nn = nn[nn > 0]
        typical = float(np.median(nn)) if len(nn) else 0.0

    edge_limit = (float(max_triangle_edge) if max_triangle_edge is not None
                  else typical * max_edge_factor if typical > 0
                  else float("inf"))
    cr_limit = (float(max_circumradius) if max_circumradius is not None
                else typical * max_circumradius_factor if typical > 0
                else float("inf"))
    if math.isfinite(edge_limit) or math.isfinite(cr_limit):
        boundary_notes.append(
            f"实测点典型间距 {typical:.2f} m；边长限值 {edge_limit:.2f} m、"
            f"外接圆半径限值 {cr_limit:.2f} m（"
            f"{'用户给定' if max_circumradius is not None else 'α-shape 自动估计'}"
            "）。超限三角片视为跨越缺测区，拒绝并计入未覆盖面积，绝不外推。"
        )

    prepared_domain = prep(domain)
    domain_covers = prepared_domain.covers

    kept_tris: list[list[int]] = []
    degraded: list[dict] = []
    rejected_outside = 0
    rejected_cross = 0
    rejected_longedge = 0
    rejected_circum = 0
    tri_polys: list = []

    for simp in tri.simplices:
        a, b, c = [int(k) for k in simp]
        coords = xy[[a, b, c]]
        q = _triangle_quality(coords)
        if q["area"] < min_area:
            degraded.append({
                "vertices": [point_ids[a], point_ids[b], point_ids[c]],
                "reason": "near_zero_area",
                **q,
                "message": "三角形面积接近 0（共线/重合点），已剔除",
            })
            continue
        if q["min_angle"] < min_angle_deg:
            degraded.append({
                "vertices": [point_ids[a], point_ids[b], point_ids[c]],
                "reason": "sliver_triangle",
                **q,
                "message": f"最小角 {q['min_angle']:.2f}° 为狭长片，结果不可靠，已剔除",
            })
            continue
        if q["max_edge"] > edge_limit:
            rejected_longedge += 1
            continue
        cr = _circumradius(coords, q["area"])
        if cr > cr_limit:
            rejected_circum += 1
            continue

        from shapely.geometry import Point
        centroid = Point(coords.mean(axis=0))
        if not domain_covers(centroid):
            rejected_outside += 1
            continue
        tp = ShapelyPolygon(coords)
        # 边不越界：三角形位于域内 iff 三角形 ⊆ 域。用 difference 面积判定，
        # 对孔洞与凹边界都稳健。容差为片面积的 1e-9（绝对下限 1e-7 m²），
        # 仅吸收重投影/浮点的 1e-9 m 级残差。
        outside_part = tp.difference(domain)
        tol_area = max(1e-7, q["area"] * 1e-9)
        if not outside_part.is_empty and outside_part.area > tol_area:
            rejected_cross += 1
            continue

        kept_tris.append([a, b, c])
        tri_polys.append(tp)

    if not kept_tris:
        raise ValueError("没有任何三角形完整落在计量边界内，无法计算。")

    covered = unary_union(tri_polys)
    uncovered = domain.difference(covered).buffer(0)

    # 区分“沿外边界的内接缝隙”与“内部缺测洞”：
    # 与外边界相连的未覆盖片归为 boundary_gap；
    # 被已覆盖区域包围、且不碰外边界的归为 interior_gap（局部缺测）。
    boundary_gap_area = 0.0
    interior_gap_area = 0.0
    if not uncovered.is_empty:
        geoms = getattr(uncovered, "geoms", [uncovered])
        ext = domain.boundary
        for g in geoms:
            if g.is_empty:
                continue
            if g.distance(ext) < 1e-6:
                boundary_gap_area += g.area
            else:
                interior_gap_area += g.area

    from shapely.geometry import MultiPoint
    hull = MultiPoint(xy).convex_hull

    return TINResult(
        triangles=kept_tris,
        points=np.column_stack([xy, z]),
        point_ids=point_ids,
        source_indices=source_indices,
        injected_flags=injected_flags,
        degraded=degraded,
        rejected=[
            {"reason": "centroid_outside_domain", "count": rejected_outside},
            {"reason": "edge_crosses_boundary_or_hole", "count": rejected_cross},
            {"reason": "edge_exceeds_limit_crosses_missing_data",
             "count": rejected_longedge},
            {"reason": "circumradius_exceeds_alpha_crosses_missing_data",
             "count": rejected_circum},
        ],
        boundary_notes=boundary_notes,
        uncovered_geom=uncovered,
        boundary_gap_area=boundary_gap_area,
        interior_gap_area=interior_gap_area,
        covered_area=covered.area,
        domain_area=domain.area,
        hull_area=hull.area,
    )


# --------------------------------------------------------------------------
# 线性插值：在 TIN 域内用重心坐标，域外/洞/缺测处返回 None（不外推）
# --------------------------------------------------------------------------

def _barycentric(pt: np.ndarray, tri_pts: np.ndarray) -> Optional[np.ndarray]:
    """返回重心坐标；若点在三角形外（含负权）返回 None。"""
    (x1, y1), (x2, y2), (x3, y3) = tri_pts
    x, y = pt
    den = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
    if abs(den) < 1e-15:
        return None
    l1 = ((y2 - y3) * (x - x3) + (x3 - x2) * (y - y3)) / den
    l2 = ((y3 - y1) * (x - x3) + (x1 - x3) * (y - y3)) / den
    l3 = 1 - l1 - l2
    eps = -1e-9
    if l1 < eps or l2 < eps or l3 < eps:
        return None
    return np.array([l1, l2, l3])


class TINSurface:
    """TIN 线性曲面：支持单点/批量插值与三角形遍历。"""

    def __init__(self, result: TINResult):
        self.r = result
        xy = result.points[:, :2]
        self._polys = [ShapelyPolygon(xy[t]) for t in result.triangles]
        union = unary_union(self._polys)
        self._union = prep(union)
        self._tree = STRtree(self._polys)

    @property
    def area(self) -> float:
        return self.r.covered_area

    def contains(self, x: float, y: float) -> bool:
        from shapely.geometry import Point
        return self._union.covers(Point(x, y))

    def interpolate(self, x: float, y: float) -> Optional[float]:
        from shapely.geometry import Point
        p = Point(x, y)
        if not self._union.covers(p):
            return None
        for k in self._tree.query(p):
            tp = self._polys[int(k)]
            if not tp.covers(p):
                continue
            t = self.r.triangles[int(k)]
            lam = _barycentric(np.array([x, y]), self.r.points[t, :2])
            if lam is None:
                continue
            return float(lam @ self.r.points[t, 2])
        return None  # 域外 / 孔洞 / 缺测：明确无值，不做外推

    def iter_triangles_3d(self):
        """逐三角片产出 (顶点坐标 m,3 数组, 点 id 三元组, 三角形序号)。"""
        for k, t in enumerate(self.r.triangles):
            yield self.r.points[t], (
                self.r.point_ids[t[0]],
                self.r.point_ids[t[1]],
                self.r.point_ids[t[2]],
            ), k


def geojson_of(geom) -> dict:
    return mapping(geom)
