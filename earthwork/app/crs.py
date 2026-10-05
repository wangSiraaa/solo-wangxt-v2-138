"""坐标 / 高程基准转换（pyproj）。

注意：pyproj 只能完成平面基准的数学转换；高程基准（如 1985 国家高程基准
与地方理论最低潮面）之间没有纯数学关系，必须通过水准联测 / 拟合确定
偏移量或转换模型。本模块对高程仅支持“已知常数偏移”的平移，并强制
调用方确认，绝不猜测。
"""
from __future__ import annotations

from pyproj import CRS, Transformer

from .models import Datum, Point


def transform_xy(points: list[Point], src: str, dst: str) -> list[Point]:
    tr = Transformer.from_crs(CRS.from_user_input(src),
                              CRS.from_user_input(dst), always_xy=True)
    out = []
    for p in points:
        x, y = tr.transform(p.x, p.y)
        out.append(Point(id=p.id, x=float(x), y=float(y), z=p.z,
                         surface=p.surface, code=p.code))
    return out


def apply_vertical_offset(points: list[Point], offset: float,
                          confirmed: bool) -> list[Point]:
    """高程基准平移：z_new = z + offset。必须显式 confirmed=True。

    offset 必须来源于水准联测/拟合报告；软件不提供经验值。
    """
    if not confirmed:
        raise ValueError("高程基准偏移必须由联测成果给出并显式确认，软件不做猜测")
    return [Point(id=p.id, x=p.x, y=p.y, z=p.z + offset,
                  surface=p.surface, code=p.code) for p in points]


def assert_same_datum(a: Datum, b: Datum):
    if a.horizontal_crs and b.horizontal_crs and a.horizontal_crs != b.horizontal_crs:
        raise ValueError(f"平面坐标系不一致：{a.horizontal_crs} != {b.horizontal_crs}")
    if a.vertical_datum and b.vertical_datum and a.vertical_datum != b.vertical_datum:
        raise ValueError(f"高程基准不一致：{a.vertical_datum} != {b.vertical_datum}")
