"""坐标与高程基准统一。

两组数据（原地面、设计地面）必须先统一到同一平面坐标参考系与同一高程基准，
才能计算挖填量。处理原则：

1. 平面：pyproj 可用时按 EPSG 重投影；同一 CRS 直通。
2. 高程：不做任何静默假定。若垂直基准不同（例如 1985 国家高程 vs 黄海高程，
   或 GPS 椭球高 vs 正高），调用方必须显式给出 vertical_offset（设计数据
   减原地面数据的基准常数，单位米），否则抛出 DatumError。
3. 单位必须是米；以度为单位的地理坐标系不允许直接用于体积积分。

这样做是为了避免“坐标看起来重合、基准其实不一致”造成的系统性挖填偏差。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# 常见垂直基准名（仅做记录与一致性判断，不内置转换模型——各地高程异常
# 需要实测拟合，软件内硬编码常数反而危险）。
KNOWN_VERTICAL_DATUMS = {
    "1985": "1985国家高程基准",
    "1956": "1956黄海高程系",
    "wgs84_ellipsoidal": "WGS84 GPS椭球高",
    "egm2008": "EGM2008 正高",
    "local": "假定/相对高程基准",
}


class DatumError(ValueError):
    """基准无法安全统一时抛出。"""


@dataclass(frozen=True)
class DatumDecl:
    """一份数据集的基准声明。

    epsg: 平面坐标参考系 EPSG 编号（如 32650 = UTM 50N）。
    vertical_datum: 高程基准标识，见 KNOWN_VERTICAL_DATUMS。
    """
    epsg: int
    vertical_datum: str = "local"

    @property
    def key(self) -> tuple[int, str]:
        return (self.epsg, self.vertical_datum)


def _is_projected_metric(epsg: int) -> bool:
    """地理坐标系（经纬度，单位度）不能用于面积/体积计算。"""
    try:
        from pyproj import CRS
        crs = CRS.from_epsg(epsg)
        return crs.is_projected and (crs.axis_info[0].unit_name or "").lower() in (
            "metre", "meter", "m",
        )
    except Exception:
        # 无 pyproj 时无法核验；常见 UTM 段（326xx/327xx）按米放行，
        # EPSG:4326/4490 等一律拒绝。
        if 32601 <= epsg <= 32760 or epsg in (3857, 4547, 4548, 4549):
            return True
        return False


def unify(
    points: list[dict],
    src: DatumDecl,
    dst: DatumDecl,
    vertical_offset: float = 0.0,
) -> tuple[list[dict], list[str]]:
    """把点集从 src 基准转换到 dst 基准。

    points: [{"id":..., "x":..., "y":..., "z":...}, ...]
    vertical_offset: 当两高程基准不同时，调用方显式给出的常数改正
        （z_dst = z_src + offset）。基准相同时必须保持 0。
    返回 (转换后点集, 说明信息列表)。
    """
    notes: list[str] = []

    if not _is_projected_metric(dst.epsg):
        raise DatumError(
            f"目标 EPSG:{dst.epsg} 不是以米为单位的投影坐标系，"
            "不能直接积分挖填体积；请先投影到高斯/UTM 等平面坐标。"
        )

    out = [dict(p) for p in points]

    # ---- 平面 ----
    if src.epsg != dst.epsg:
        if not _is_projected_metric(src.epsg):
            raise DatumError(
                f"源 EPSG:{src.epsg} 为地理坐标（度），请确认重投影参数。"
            )
        try:
            from pyproj import Transformer
            tr = Transformer.from_crs(
                f"EPSG:{src.epsg}", f"EPSG:{dst.epsg}", always_xy=True
            )
            xs = [p["x"] for p in out]
            ys = [p["y"] for p in out]
            x2, y2 = tr.transform(xs, ys)
            for p, nx, ny in zip(out, x2, y2):
                p["x"], p["y"] = float(nx), float(ny)
            notes.append(f"平面重投影 EPSG:{src.epsg} -> EPSG:{dst.epsg}")
        except ImportError as exc:
            raise DatumError(
                "两组数据 EPSG 不同，但环境缺少 pyproj 无法重投影；"
                "请在入库前统一坐标，或安装 pyproj。"
            ) from exc

    # ---- 高程基准 ----
    if src.vertical_datum != dst.vertical_datum:
        if vertical_offset == 0.0:
            raise DatumError(
                f"高程基准不一致：{src.vertical_datum} -> {dst.vertical_datum}，"
                "且未提供 vertical_offset。本系统不会假定基准差为 0，"
                "请依据当地高程异常/水准联测结果显式提供改正数（米）。"
            )
        for p in out:
            p["z"] = p["z"] + vertical_offset
        notes.append(
            f"高程基准 {src.vertical_datum} -> {dst.vertical_datum}，"
            f"常数改正 {vertical_offset:+.4f} m（调用方显式提供）"
        )

    return out, notes
