"""原地面 TIN 与设计面 TIN 的叠加。

范围（不外推原则）：只在“原地面 TIN 覆盖 ∩ 设计面 TIN 覆盖 ∩ 边界范围”
内积分。任一面没有数据的区域一律不计算、不补点、不趋势外推。

剖分：把设计三角网的边（在公共区域内的部分）与每个原地面裁剪片的边界
一起 node + polygonize，得到叠加单元。单元内原地面是一个平面、设计面也是
一个平面，故差值为线性面；单元再 earcut 成耳三角片后按 volume 精确积分。
"""
from __future__ import annotations

import numpy as np
import mapbox_earcut as earcut
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import polygonize, unary_union

from .geometry import signed_area
from .volume import tri_cut_fill


def _oriented_rings(poly) -> tuple[np.ndarray, list[np.ndarray]]:
    """返回 (逆时针外环, 顺时针洞环列表)，坐标不闭合。"""
    ext = np.asarray(poly.exterior.coords)[:-1]
    if signed_area(ext) < 0:
        ext = ext[::-1]
    holes = []
    for r in poly.interiors:
        h = np.asarray(r.coords)[:-1]
        if signed_area(h) > 0:
            h = h[::-1]
        holes.append(h)
    return ext, holes


def _earcut_polygon(poly) -> np.ndarray:
    ext, holes = _oriented_rings(poly)
    verts = [ext] + holes
    coords = np.vstack(verts).astype(np.float64)
    ends = np.cumsum([len(v) for v in verts], dtype=np.uint32)
    tris = earcut.triangulate_float64(coords, ends)
    return tris.reshape(-1, 3), coords


def _design_edges(design_tin):
    """设计 TIN 所有三角边（去重）。"""
    edges: dict[tuple[int, int], LineString] = {}
    for s in design_tin.tri.simplices:
        for i, j in ((0, 1), (1, 2), (2, 0)):
            a, b = int(s[i]), int(s[j])
            key = (a, b) if a < b else (b, a)
            if key not in edges:
                p0 = design_tin.coords[a]
                p1 = design_tin.coords[b]
                edges[key] = LineString([p0, p1])
    return edges


def build_facets(ground_tin, design_tin, progress=None):
    """生成全部耳三角片挖填明细。

    返回 (facets, common_area, ground_outside_design_area, cells_info)。
    facets: 每项是 dict，字段对齐 models.FacetDetail。
    """
    d_edges = _design_edges(design_tin)
    edge_geoms = list(d_edges.values())
    # 空间索引：用 shapely STRtree 快速筛出可能穿过地图片的设计边
    try:
        from shapely.strtree import STRtree
        tree = STRtree(edge_geoms)
        has_tree = True
    except Exception:
        has_tree = False

    common_region = ground_tin.region.intersection(design_tin.region)

    facets: list[dict] = []
    cells_info: list[dict] = []
    common_area_total = 0.0
    outside_design_area = 0.0
    facet_id = 0
    cell_id = 0

    for piece in ground_tin.pieces:
        kind, gtri, gpoly = piece
        if kind == "tri":
            pts = ground_tin.simplices_xy(gtri)
            gp = __import__("shapely").geometry.Polygon(pts)
        else:
            gp = gpoly

        common = gp.intersection(common_region)
        if common.is_empty or common.area < 1e-9:
            outside_design_area += gp.area
            continue
        outside_design_area += gp.area - common.area
        common_area_total += common.area

        # 收集公共区域内的设计边片段
        cand = tree.query(common) if has_tree else range(len(edge_geoms))
        lines: list[LineString] = []
        for k in cand:
            e = edge_geoms[int(k)]
            inter = e.intersection(common)
            if inter.is_empty:
                continue
            if inter.geom_type == "LineString" and inter.length > 1e-9:
                lines.append(inter)
            elif inter.geom_type == "MultiLineString":
                for part in inter.geoms:
                    if part.length > 1e-9:
                        lines.append(part)

        # 公共区域的边界环（外环+洞环）也加入线集，polygonize 才能封闭出单元
        polys_common = common.geoms if common.geom_type in (
            "MultiPolygon", "GeometryCollection") else [common]
        boundary_lines: list[LineString] = []
        for cp in polys_common:
            if cp.geom_type != "Polygon":
                continue
            boundary_lines.append(LineString(cp.exterior.coords))
            for r in cp.interiors:
                boundary_lines.append(LineString(r.coords))

        noded = unary_union(lines + boundary_lines)
        cell_polys = [p for p in polygonize(noded)
                      if p.area > 1e-9 and common.covers(p.representative_point())]

        for cp in cell_polys:
            cell_id += 1
            tris, coords = _earcut_polygon(cp)
            if len(tris) == 0:
                continue

            # 原地面高程：该裁剪片属于单一原地面三角片，向量化线性插值
            zg = ground_tin.z_on_tri(gtri, coords)

            # 设计面高程：逐点在设计 Delaunay 上定位。单元是两面凸包的交集
            # 多边形，边上相邻片插值连续；凸包外定位失败的点直接剔除该耳片，
            # 绝不用相邻片外推（边界外不擅自外推原则）。
            zd = np.full(len(coords), np.nan)
            dt_per_v: list[int | None] = []
            for i, xy in enumerate(coords):
                loc = design_tin.locate(float(xy[0]), float(xy[1]))
                if loc is None:
                    dt_per_v.append(None)
                else:
                    t, (w0, w1, w2) = loc
                    j0, j1, j2 = design_tin.tri.simplices[t]
                    zd[i] = w0 * design_tin.z[j0] + w1 * design_tin.z[j1] + w2 * design_tin.z[j2]
                    dt_per_v.append(int(t))

            g_verts = [int(x) for x in ground_tin.tri.simplices[gtri]]
            # 质心所在设计片仅用于单元溯源标注，不用于外推赋值
            cen = np.asarray(cp.representative_point().coords[0])
            cen_loc = design_tin.locate(cen[0], cen[1])
            fallback_t = cen_loc[0] if cen_loc else None
            for tri_idx in tris:
                v = coords[tri_idx]
                dvg = zg[tri_idx]
                dvd = zd[tri_idx]
                if np.any(np.isnan(dvd)):
                    continue  # 设计面无数据点：不外推，跳过
                dz = dvg - dvd
                ca, fa, cv, fv = tri_cut_fill(v, dz)
                d_tris = [dt_per_v[k] for k in tri_idx]
                facets.append({
                    "facet_id": facet_id,
                    "cell_id": cell_id,
                    "vertices": [(float(p[0]), float(p[1])) for p in v],
                    "z_ground": [float(x) for x in dvg],
                    "z_design": [float(x) for x in dvd],
                    "dz": [float(x) for x in dz],
                    "area": float(abs(signed_area(v))),
                    "cut": float(cv),
                    "fill": float(fv),
                    "cut_area": float(ca),
                    "fill_area": float(fa),
                    "source_ground_tri": g_verts,
                    "source_design_tri": d_tris,
                })
                facet_id += 1

            cells_info.append({
                "cell_id": cell_id,
                "ground_tri": g_verts,
                "design_tri": (
                    [int(x) for x in design_tin.tri.simplices[fallback_t]]
                    if fallback_t is not None else None),                "area": float(cp.area),
                "n_vertices": len(coords),
            })

        if progress:
            progress(cell_id, facet_id)

    return facets, float(common_area_total), float(outside_design_area), cells_info
