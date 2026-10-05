"""算法正确性与工程纪律校验。

手算基准：
  平面坡地 z_g=0.02x，设计 z=1.0，100×100：
      V_cut = V_fill = 2500 m³，净 0，总搬运 5000
  中央 20×20 孔洞（沿 x 轴占 [40,60]，跨零线两侧各切掉 20 m³）：
      V_cut = V_fill = 2480 m³
  断面 y=const：cut_area = fill_area = 25 m²
"""
import math
import pytest

from app.geo.fixtures import ALL_CASES
from app.geo.engine import run_scheme
from app.geo.datum import DatumDecl, unify, DatumError


@pytest.fixture(scope="module")
def results():
    return {k: run_scheme(ALL_CASES[k]()["payload"]) for k in ALL_CASES}


def test_slope_exact_analytic(results):
    v = results["slope"]["volume"]
    assert v["cut_volume_m3"] == pytest.approx(2500.0, abs=1e-6)
    assert v["fill_volume_m3"] == pytest.approx(2500.0, abs=1e-6)
    assert v["net_volume_m3"] == pytest.approx(0.0, abs=1e-6)
    assert v["gross_movement_m3"] == pytest.approx(5000.0, abs=1e-6)
    assert v["area_evaluated_m2"] == pytest.approx(10000.0, abs=1e-6)


def test_hole_exact_analytic(results):
    v = results["hole"]["volume"]
    assert v["cut_volume_m3"] == pytest.approx(2480.0, abs=1e-6)
    assert v["fill_volume_m3"] == pytest.approx(2480., abs=1e-6)
    assert v["area_evaluated_m2"] == pytest.approx(9600.0, abs=1e-6)
    assert v["area_not_evaluated_m2"] == pytest.approx(0.0, abs=1e-6)


def test_section_areas_analytic(results):
    for sec in results["slope"]["sections"]:
        assert sec["cut_area_m2"] == pytest.approx(25.0, abs=1e-6)
        assert sec["fill_area_m2"] == pytest.approx(25.0, abs=1e-6)
    sec_hole = results["hole"]["sections"][0]
    # 过孔洞断面：[0,40] 填 = (1+0.2)/2*40 = 24；[60,100] 挖 = (0.2+1)/2*40 = 24
    assert sec_hole["cut_area_m2"] == pytest.approx(24.0, abs=1e-6)
    assert sec_hole["fill_area_m2"] == pytest.approx(24.0, abs=1e-6)


def test_grid_converges_to_tin(results):
    r = results["slope"]
    exact = r["volume"]["gross_movement_m3"]
    errors = [abs(g["gross_movement_m3"] - exact) for g in r["grid_compare"]]
    # 10/5/2 m 网格全部命中精确值（零线在网格线上的特例）；至少保证单调不增
    assert errors == sorted(errors, reverse=True)
    assert errors[-1] <= 1.0


def test_no_extrapolation_outside_missing(results):
    r = results["missing"]
    t, v = r["tin"]["ground"], r["volume"]
    # 中央 40×40 缺测：内部未覆盖面积 > 0（约 1400 m²，四角半格为合法内插）
    assert t["interior_gap_area_m2"] > 1000
    assert v["area_evaluated_m2"] + v["area_not_evaluated_m2"] == \
        pytest.approx(10000.0, abs=1e-6)
    # 断面在缺测段必须断开（ground_z 含 None），不得补出高程
    sec = r["sections"][0]
    assert any(z is None for z in sec["ground_z"])


def test_dirty_data_listed_not_silently_dropped(results):
    q = results["dirty"]["quality"]["ground"]["issues"]
    kinds = [i["type"] for i in q]
    assert kinds.count("duplicate_xyz") == 1
    assert kinds.count("z_conflict") == 1
    assert kinds.count("outside_boundary") == 1
    assert kinds.count("nonfinite") == 1
    # 冲突高程均值 2.175 注入，体积仍可算
    v = results["dirty"]["volume"]
    assert v["cell_count"] > 0


def test_design_tin_equals_plane_when_coplanar(results):
    """用与平面 z=1 完全重合的设计点 TIN 计算，必须与平面设计面同结果。"""
    payload = {**ALL_CASES["slope"]()["payload"]}
    payload["design"] = {
        "kind": "points", "epsg": 32650,
        "points": [
            {"id": "d1", "x": 0, "y": 0, "z": 1.0},
            {"id": "d2", "x": 100, "y": 0, "z": 1.0},
            {"id": "d3", "x": 100, "y": 100, "z": 1.0},
            {"id": "d4", "x": 0, "y": 100, "z": 1.0},
        ],
    }
    r = run_scheme(payload)
    assert r["volume"]["cut_volume_m3"] == pytest.approx(2500.0, abs=1e-6)
    assert r["volume"]["fill_volume_m3"] == pytest.approx(2500.0, abs=1e-6)


def test_vertical_datum_conflict_requires_explicit_offset():
    pts = [{"id": 1, "x": 0, "y": 0, "z": 0},
           {"id": 2, "x": 100, "y": 0, "z": 2},
           {"id": 3, "x": 100, "y": 100, "z": 2}]
    with pytest.raises(DatumError):
        unify(pts, DatumDecl(32650, "wgs84_ellipsoidal"),
              DatumDecl(32650, "1985"))
    out, notes = unify(pts, DatumDecl(32650, "wgs84_ellipsoidal"),
                       DatumDecl(32650, "1985"), vertical_offset=-0.034)
    assert out[0]["z"] == pytest.approx(-0.034)
    assert any("高程基准" in n for n in notes)


def test_geographic_crs_rejected():
    pts = [{"id": 1, "x": 0, "y": 0, "z": 0},
           {"id": 2, "x": 1, "y": 0, "z": 2},
           {"id": 3, "x": 1, "y": 1, "z": 2}]
    with pytest.raises(DatumError):
        unify(pts, DatumDecl(4326), DatumDecl(4326))


def test_cut_fill_reported_separately(results):
    """任何算例都必须同时给出 cut 与 fill，净值不能替代分量。"""
    for k, r in results.items():
        v = r["volume"]
        assert "cut_volume_m3" in v and "fill_volume_m3" in v
        assert "gross_movement_m3" in v
    # 坡地净值 0，但挖填各 2500——核心纪律
    r = results["slope"]["volume"]
    assert abs(r["net_volume_m3"]) < 1e-9
    assert r["cut_volume_m3"] > 0 and r["fill_volume_m3"] > 0
