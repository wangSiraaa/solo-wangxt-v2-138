"""请求模型（宽松校验：点集直接透传，几何为 GeoJSON dict）。"""
from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class PointIn(BaseModel):
    id: Optional[Any] = None
    x: float
    y: float
    z: float


class DatasetIn(BaseModel):
    epsg: int
    vertical_datum: str = "local"
    vertical_offset: float = 0.0
    points: list[PointIn]


class DesignIn(BaseModel):
    kind: str = "plane"
    a: Optional[float] = None
    b: Optional[float] = None
    c: Optional[float] = None
    points: Optional[list[PointIn]] = None
    epsg: Optional[int] = None
    vertical_datum: str = "local"
    vertical_offset: float = 0.0


class SectionIn(BaseModel):
    name: str = "断面"
    line: list[list[float]]
    step: float = 1.0


class SchemeRequest(BaseModel):
    name: Optional[str] = "未命名方案"
    target_epsg: int
    target_vertical_datum: str = "local"
    boundary: dict
    ground: dict
    design: dict
    grid_spacings: list[float] = Field(default_factory=lambda: [10.0, 5.0, 2.0])
    sections: list[dict] = Field(default_factory=list)
    max_triangle_edge: Optional[float] = None
    max_circumradius: Optional[float] = None
    persist: bool = True


class DrillRequest(BaseModel):
    """从汇总下钻：按 cell / ground 三角形 / 断面返回明细。"""
    case: Optional[str] = None
    payload: Optional[dict] = None
    scheme_id: Optional[int] = None
