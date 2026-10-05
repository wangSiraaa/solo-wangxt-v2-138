"""计算编排：质量检查 -> 基准统一 -> 限定 TIN -> 挖填积分 -> 网格对比 -> 断面。

一次方案计算返回：
- 汇总（挖、填、净、总搬运、覆盖面积、未评价面积）；
- 问题清单（重复点、高程冲突、退化三角片、边界外点、缺测面积）；
- 三角片级 cell 明细，供前端从汇总下钻；
- 多个网格步长对比；
- 断面结果。
"""
from __future__ import annotations

from .boundary import parse_boundary, boundary_info
from .datum import DatumDecl, unify, DatumError
from .quality import check_points
from .tin import build_constrained_tin, TINSurface, geojson_of
from .design import build_design_surface
from .volume import integrate_tin_vs_surface, integrate_grid
from .section import sample_section


def run_scheme(payload: dict) -> dict:
    """payload 结构见 schemas.SchemeRequest。"""
    warnings: list[str] = []

    # 1) 边界
    domain_mp = parse_boundary(payload["boundary"])
    binfo = boundary_info(domain_mp)
    # 积分在单个 Polygon/多片上均可（Shapely 交集天然处理）；
    # 为 STRtree 稳定，取 MultiPolygon 整体传入。
    domain = domain_mp

    # 2) 基准统一
    target = DatumDecl(
        epsg=int(payload["target_epsg"]),
        vertical_datum=payload.get("target_vertical_datum", "local"),
    )
    g_decl = DatumDecl(
        epsg=int(payload["ground"]["epsg"]),
        vertical_datum=payload["ground"].get("vertical_datum", "local"),
    )
    g_pts, g_notes = unify(
        payload["ground"]["points"], g_decl, target,
        vertical_offset=float(payload["ground"].get("vertical_offset", 0.0)),
    )
    warnings.extend(g_notes)

    design = payload["design"]
    d_pts = None
    if design.get("kind") == "points":
        d_decl = DatumDecl(
            epsg=int(design["epsg"]),
            vertical_datum=design.get("vertical_datum", "local"),
        )
        d_pts, d_notes = unify(
            design["points"], d_decl, target,
            vertical_offset=float(design.get("vertical_offset", 0.0)),
        )
        warnings.extend(d_notes)

    # 3) 质检（原地面；设计点同样检查）
    g_qc = check_points(g_pts, domain)
    qc_blocks = {"ground": _qc_json(g_qc, g_pts)}
    if d_pts is not None:
        d_qc = check_points(d_pts, domain)
        qc_blocks["design"] = _qc_json(d_qc, d_pts)
    else:
        qc_blocks["design"] = None

    # 4) 限定 TIN
    max_edge = payload.get("max_triangle_edge")
    max_cr = payload.get("max_circumradius")
    tin_kw = {}
    if max_edge is not None:
        tin_kw["max_triangle_edge"] = float(max_edge)
    if max_cr is not None:
        tin_kw["max_circumradius"] = float(max_cr)
    g_tinres = build_constrained_tin(g_pts, domain, g_qc["keep"], **tin_kw)
    ground = TINSurface(g_tinres)

    if design.get("kind") == "points":
        design_ds = TINSurface(
            build_constrained_tin(d_pts, domain, d_qc["keep"], **tin_kw))
        d_kind = "tin"
    else:
        design_ds, d_kind = build_design_surface(design, domain)

    # 5) TIN 精确积分
    rep = integrate_tin_vs_surface(ground, design_ds, domain, d_kind)
    warnings.extend(rep.warnings)

    # 6) 网格精度对比（默认 10/5/2 m；可在 payload 指定）
    grid_compare = []
    for sp in payload.get("grid_spacings", [10.0, 5.0, 2.0]):
        gr = integrate_grid(ground, design_ds, domain, float(sp), d_kind)
        grid_compare.append(gr.summary())

    # 7) 断面
    sections = []
    for sec in payload.get("sections", []):
        sr = sample_section(
            ground, design_ds, d_kind,
            [tuple(c) for c in sec["line"]],
            step=float(sec.get("step", 1.0)),
        )
        sections.append({
            "name": sec.get("name", "断面"),
            "cut_area_m2": round(sr.cut_area, 4),
            "fill_area_m2": round(sr.fill_area, 4),
            "valid_range_m": sr.valid_range,
            "stations": sr.stations,
            "ground_z": sr.ground_z,
            "design_z": sr.design_z,
            "warnings": sr.warnings,
        })

    # 8) 三角片/单元明细（下钻）
    cells = [{
        "cell_id": c.cell_id,
        "ground_tri": c.ground_tri,
        "design_tri": c.design_tri,
        "area_m2": round(c.area, 5),
        "cut_m3": round(c.cut, 5),
        "fill_m3": round(c.fill, 5),
        "mean_diff_m": round(c.mean_diff, 5),
        "polygon": [[round(x, 3), round(y, 3)] for x, y in c.polygon],
    } for c in rep.cells]

    # 三角片几何（供 3D/2D 着色）
    gtris = []
    for verts, ids, k in ground.iter_triangles_3d():
        gtris.append({
            "tri": k,
            "point_ids": list(ids),
            "vertices": [[round(float(v[0]), 3), round(float(v[1]), 3),
                          round(float(v[2]), 3)] for v in verts],
        })

    def _tri_dump(surface):
        out = []
        for verts, ids, k in surface.iter_triangles_3d():
            out.append([[round(float(v[0]), 3), round(float(v[1]), 3),
                         round(float(v[2]), 3)] for v in verts])
        return out

    d_tris = _tri_dump(design_ds) if d_kind == "tin" else []
    # 平面设计面：沿地面 TIN 每个三角片取顶点处设计高程，形成与原地面
    # 同拓扑的设计网格，便于三维对照
    if d_kind == "plane":
        a, b, c = design_ds.coeff
        d_tris = [
            [[v[0], v[1], round(a * v[0] + b * v[1] + c, 3)]
             for v in t["vertices"]]
            for t in gtris
        ]

    return {
        "crs": {"epsg": target.epsg, "vertical_datum": target.vertical_datum},
        "boundary": binfo,
        "datum_notes": warnings,
        "design_describe": design_ds.describe() if hasattr(design_ds, "describe")
        else {"kind": "tin", "triangles": len(design_ds.r.triangles)},
        "quality": qc_blocks,
        "tin": {
            "ground": {
                "points_used": len(g_tinres.points),
                "triangles": len(g_tinres.triangles),
                "covered_area_m2": round(g_tinres.covered_area, 4),
                "domain_area_m2": round(g_tinres.domain_area, 4),
                "boundary_gap_area_m2": round(g_tinres.boundary_gap_area, 4),
                "interior_gap_area_m2": round(g_tinres.interior_gap_area, 4),
                "degraded": g_tinres.degraded,
                "rejected": g_tinres.rejected,
                "boundary_notes": g_tinres.boundary_notes,
                "injected_points": g_tinres.injected_flags,
                "uncovered_geojson": geojson_of(g_tinres.uncovered_geom),
                "triangles": gtris,
                "points": [[round(float(p[0]), 3), round(float(p[1]), 3),
                            round(float(p[2]), 3)] for p in g_tinres.points],
                "point_ids": [str(x) for x in g_tinres.point_ids],
                "source_indices": g_tinres.source_indices,
            }
        },
        "design_mesh": {"kind": d_kind, "triangles": d_tris},
        "volume": rep.summary(),
        "cells": cells,
        "grid_compare": grid_compare,
        "sections": sections,
    }


def _qc_json(qc: dict, pts: list[dict]) -> dict:
    return {"summary": qc["summary"], "issues": qc["issues"]}
