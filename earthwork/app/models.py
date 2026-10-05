"""请求 / 响应数据模型（pydantic v2）。"""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class Point(BaseModel):
    """一个三维高程点。

    surface: "ground" 原地面实测点，"design" 设计地面点。
    """

    id: Optional[str] = None
    x: float
    y: float
    z: float
    surface: Literal["ground", "design"] = "ground"
    code: Optional[str] = None  # 测点编码，如地形点/断面点


class Ring(BaseModel):
    """边界环：外环按逆时针、洞环按顺时针给出（GeoJSON 习惯）。"""

    coords: list[tuple[float, float]]
    is_hole: bool = False


class Datum(BaseModel):
    """坐标与高程基准信息——两组数据必须统一，否则拒绝计算。"""

    horizontal_crs: Optional[str] = None  # 如 "EPSG:4547"(CGCS2000 3度带)
    vertical_datum: Optional[str] = None  # 如 "1985国家高程基准"
    units: str = "m"


class Project(BaseModel):
    """一个挖填方案：点集 + 边界 + 基准。"""

    name: str
    points: list[Point] = Field(default_factory=list)
    boundary: Optional[list[Ring]] = None  # 空=点集凸包
    holes: list[list[tuple[float, float]]] = Field(default_factory=list)
    no_data: list[list[tuple[float, float]]] = Field(default_factory=list)  # 缺测区
    datum: Datum = Field(default_factory=Datum)
    design_datum: Optional[Datum] = None  # 若给出，必须与 datum 一致，否则报错


class ComputeOptions(BaseModel):
    grid_size: float = 20.0          # 规则网格边长(m)，用于对比
    section_spacing: float = 20.0    # 断面间距(m)
    section_width: Optional[float] = None  # 断面带宽(矩形柱近似时使用)
    section_line: Optional[list[tuple[float, float]]] = None  # 指定断面线
    gap_max_area: float = 400.0      # 大于此面积(m²)的瘦长/缺测三角片判为疑似缺测
    gap_min_quality: float = 0.02    # 三角片质量(2r/R)低于该值且面积大时判退化
    grid_method: Literal["corner", "prismoid"] = "corner"


class SurfaceSummary(BaseModel):
    n_points: int
    n_triangles: int
    n_clipped: int          # 被边界裁掉的原始三角片数
    extent: tuple[float, float, float, float]


class VolumeTotals(BaseModel):
    cut: float              # 挖方体积 m³（原地面高于设计面部分）
    fill: float             # 填方体积 m³
    net: float              # = cut - fill，仅作参考，禁止用于代替挖、填分别计量
    area: float             # 参与计算的平面面积 m²
    area_cut: float
    area_fill: float
    area_flat: float
    max_depth_cut: float
    max_depth_fill: float


class QCIssue(BaseModel):
    kind: str               # duplicate_exact | duplicate_conflict | degenerate | outside | oversized | datum
    severity: Literal["error", "warning", "info"]
    message: str
    coords: Optional[list[tuple[float, float]]] = None
    triangle: Optional[list[tuple[float, float]]] = None
    values: Optional[dict] = None


class FacetDetail(BaseModel):
    """汇总量下钻的最小单元：一个剖分单元多边形内的一个耳三角片。"""

    facet_id: int
    cell_id: int
    vertices: list[tuple[float, float]]
    z_ground: list[float]
    z_design: list[float]
    dz: list[float]
    area: float
    cut: float
    fill: float
    cut_area: float
    fill_area: float
    source_ground_tri: list[int]   # 原地面 TIN 三角片顶点索引(全局点号)
    source_design_tri: list[int | None]
    in_hole: bool = False


class GridResult(BaseModel):
    size: float
    method: str
    cut: float
    fill: float
    net: float
    area: float
    n_cells: int
    n_cells_used: int
    diff_cut_vs_tin: float
    diff_fill_vs_tin: float
    rel_cut_pct: float
    rel_fill_pct: float


class SectionResult(BaseModel):
    name: str
    line: list[tuple[float, float]]
    s: list[float]
    z_ground: list[float | None]
    z_design: list[float | None]
    cut_area: float         # 断面线上挖方面积 m²（单位带宽意义见报告）
    fill_area: float
    length: float


class ComputeResult(BaseModel):
    project_name: str
    datum: Datum
    ground: SurfaceSummary
    design: SurfaceSummary
    totals: VolumeTotals
    grid: GridResult
    grid_compare: list[GridResult]
    sections: list[SectionResult]
    section_volume: dict = Field(default_factory=dict)
    issues: list[QCIssue]
    facets: list[FacetDetail]
    # 供三维渲染的几何（坐标仍是工程坐标，前端归心显示）
    tin_ground: list[list[int]]
    tin_design: list[list[int]]
    points: list[Point]
    boundary: Optional[list[Ring]]
    holes: list[list[tuple[float, float]]]
    no_data: list[list[tuple[float, float]]]
    uncovered_area: float
    disclaimer: str


DISCLAIMER = (
    "本结果为软件按给定高程点、边界与统一基准计算的算例量，"
    "仅用于设计复核与方案比选，不替代现场实测、监理签认与计量认定。"
)
