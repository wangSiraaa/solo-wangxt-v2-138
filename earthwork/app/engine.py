"""计算编排：去重 -> 双 TIN -> 叠加积分 -> 网格/断面 -> 汇总下钻。"""
from __future__ import annotations

import numpy as np

from .grid import compare_grids
from .models import (ComputeOptions, ComputeResult, DISCLAIMER, FacetDetail,
                     SurfaceSummary, VolumeTotals)
from .overlay import build_facets
from .qc import run_qc
from .sections import grid_sections, sample_section, section_volume
from .tin import build_tin


def _dedup(points):
    """重复点去重：返回 (保留点, 被删点索引)。高程矛盾点保留全部，交由 QC 报错。"""
    kept, drop = [], set()
    bucket: dict[tuple, int] = {}
    for i, p in enumerate(points):
        key = (round(p.x / 1e-3), round(p.y / 1e-3))
        if key in bucket:
            j = bucket[key]
            if abs(kept[j].z - p.z) <= 1e-3:
                drop.add(i)
                continue
        bucket[key] = len(kept)
        kept.append(p)
    return kept, drop


def compute(project, options: ComputeOptions | None = None) -> ComputeResult:
    options = options or ComputeOptions()
    points = project.points
    raw_ground_pts = [p for p in points if p.surface == "ground"]
    raw_design_pts = [p for p in points if p.surface == "design"]
    if len(raw_ground_pts) < 3 or len(raw_design_pts) < 3:
        raise ValueError("原地面与设计面各至少需要 3 个高程点")

    ground_pts, _ = _dedup(raw_ground_pts)
    design_pts, _ = _dedup(raw_design_pts)

    outer = project.boundary[0].coords if project.boundary else None
    holes = [r.coords for r in project.boundary[1:]] if project.boundary else project.holes

    gcoords = np.array([[p.x, p.y] for p in ground_pts])
    gz = np.array([p.z for p in ground_pts])
    dcoords = np.array([[p.x, p.y] for p in design_pts])
    dzp = np.array([p.z for p in design_pts])

    gt = build_tin("原地面", gcoords, gz, outer, holes, project.no_data)
    dt = build_tin("设计面", dcoords, dzp, outer, holes, project.no_data)

    facets, common_area, uncovered_area, cells = build_facets(gt, dt)

    cut = sum(f["cut"] for f in facets)
    fill = sum(f["fill"] for f in facets)
    area_cut = sum(f["cut_area"] for f in facets)
    area_fill = sum(f["fill_area"] for f in facets)
    max_cut = max((max(f["dz"]) for f in facets), default=0.0)
    max_fill = max((-min(f["dz"]) for f in facets), default=0.0)
    totals = VolumeTotals(
        cut=cut, fill=fill, net=cut - fill,
        area=common_area, area_cut=area_cut, area_fill=area_fill,
        area_flat=max(common_area - area_cut - area_fill, 0.0),
        max_depth_cut=max(max_cut, 0.0), max_depth_fill=max(max_fill, 0.0))

    # 网格法多档对比
    sizes = sorted(set([options.grid_size, 10, 25, 40]))
    grid_results = compare_grids(gt, dt, sizes=sizes,
                                 tin_cut=cut, tin_fill=fill)
    main_grid = next((g for g in grid_results
                      if abs(g.size - options.grid_size) < 1e-9), grid_results[0])

    # 断面
    if options.section_line:
        sections = [sample_section(gt, dt, options.section_line,
                                   step=max(options.section_spacing / 10, 1.0))]
    else:
        sections = grid_sections(gt, dt, options.section_spacing, "x")
    sec_vol = section_volume(sections)

    issues = run_qc(raw_ground_pts, raw_design_pts, gt, dt,
                    project.datum, project.design_datum,
                    options.gap_max_area, options.gap_min_quality)

    def _summary(tin):
        return SurfaceSummary(
            n_points=len(tin.coords),
            n_triangles=sum(1 for p in tin.pieces if p[0] == "tri")
                         + sum(1 for p in tin.pieces if p[0] == "frag"),
            n_clipped=tin.n_clipped, extent=tin.extent)

    facet_models = [FacetDetail(**f) for f in facets]

    return ComputeResult(
        project_name=project.name, datum=project.datum,
        ground=_summary(gt), design=_summary(dt),
        totals=totals, grid=main_grid, grid_compare=grid_results,
        sections=sections, section_volume=sec_vol,
        issues=issues, facets=facet_models,
        tin_ground=[[int(i) for i in s] for s in gt.tri.simplices],
        tin_design=[[int(i) for i in s] for s in dt.tri.simplices],
        points=ground_pts + design_pts,
        boundary=project.boundary,
        holes=project.holes, no_data=project.no_data,
        uncovered_area=uncovered_area,
        disclaimer=DISCLAIMER,
    )
