"""计量边界：外环 + 孔洞（Shapely）。

边界来源为 GeoJSON Polygon / MultiPolygon 或显式坐标。
孔洞（holes）表示计量区内被扣除的区域（既有构筑物、保留体等），
与“局部缺测”语义不同：孔洞是明确不计量，缺测是无数据。
"""
from __future__ import annotations

from shapely.geometry import Polygon, MultiPolygon, mapping, shape
from shapely.geometry.polygon import orient


class BoundaryError(ValueError):
    pass


def parse_boundary(geom: dict | Polygon | MultiPolygon) -> MultiPolygon:
    """归一化为 MultiPolygon；外环逆时针、孔洞顺时针（Shapely 内部表示）。"""
    if isinstance(geom, (Polygon, MultiPolygon)):
        g = geom
    elif isinstance(geom, dict):
        g = shape(geom)
    else:
        raise BoundaryError("边界必须是 GeoJSON Polygon/MultiPolygon")

    if g.geom_type not in ("Polygon", "MultiPolygon"):
        raise BoundaryError(f"不支持的几何类型: {g.geom_type}")
    if not g.is_valid:
        raise BoundaryError(f"边界几何无效（自交或环方向异常）: {g.is_valid}")

    polys = [g] if g.geom_type == "Polygon" else list(g.geoms)
    fixed = []
    for p in polys:
        if p.exterior is None or len(p.exterior.coords) < 4:
            raise BoundaryError("外环至少需要 3 个不同点（首尾闭合）")
        fixed.append(orient(p, sign=1.0))
    return MultiPolygon(fixed) if len(fixed) > 1 else MultiPolygon([fixed[0]])


def boundary_info(mp: MultiPolygon) -> dict:
    holes = sum(len(p.interiors) for p in mp.geoms)
    return {
        "type": "MultiPolygon",
        "parts": len(mp.geoms),
        "holes": holes,
        "area_m2": mp.area,
        "bounds": dict(zip(("minx", "miny", "maxx", "maxy"), mp.bounds)),
        "perimeter_m": mp.length,
        "geojson": mapping(mp),
    }
