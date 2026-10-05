"""算法正确性测试：以平面坡地可手算案例为基准。

解析解：
  zg=0.05x, zd=0.05y, 100x100 正方形
  cut = fill = 0.05 * 100³/6 = 8333.333... m³
  挖填面积各 5000 m²，最大挖/填深均 5 m。
"""
import math

import numpy as np
import pytest

from app.cases import (case_gap, case_hole, case_plane, case_qc,
                       case_rolling)
from app.models import ComputeOptions
from app.engine import compute
from app.volume import tri_cut_fill


class TestTriCutFill:
    def test_all_cut(self):
        v = np.array([[0, 0], [1, 0], [0, 1]], float)
        ca, fa, cv, fv = tri_cut_fill(v, np.array([2.0, 4.0, 6.0]))
        assert fa == 0 and fv == 0
        assert ca == pytest.approx(0.5)
        assert cv == pytest.approx(0.5 * (2 + 4 + 6) / 3)

    def test_all_fill(self):
        v = np.array([[0, 0], [1, 0], [0, 1]], float)
        ca, fa, cv, fv = tri_cut_fill(v, np.array([-2.0, -4.0, -6.0]))
        assert ca == 0 and cv == 0
        assert fv == pytest.approx(0.5 * (2 + 4 + 6) / 3)

    def test_cross_zero_symmetric(self):
        # 直角等腰三角形，dz=(1,-1,0)：挖填各半，净 0
        v = np.array([[0, 0], [1, 0], [1, 1]], float)
        ca, fa, cv, fv = tri_cut_fill(v, np.array([1.0, -1.0, 0.0]))
        assert ca == pytest.approx(0.25, abs=1e-9)
        assert fa == pytest.approx(0.25, abs=1e-9)
        assert cv == pytest.approx(fv, abs=1e-12)
        assert cv == pytest.approx(1 / 12, abs=1e-9)

    def test_net_not_masking(self):
        # 挖填都很大但净量为 0 时，两者必须分别保留
        v = np.array([[0, 0], [10, 0], [0, 10]], float)
        ca, fa, cv, fv = tri_cut_fill(v, np.array([9.0, -9.0, 0.0]))
        assert cv > 50 and fv > 50
        assert cv == pytest.approx(fv, rel=1e-9)
        assert cv == pytest.approx(75.0, abs=1e-9)  # 挖=填，净量为0但量值很大


class TestPlaneCase:
    @pytest.fixture(scope="class")
    @classmethod
    def result(cls):
        return compute(case_plane(), ComputeOptions(
            grid_size=20, section_spacing=50))

    def test_hand_calc_volumes(self, result):
        t = result.totals
        assert t.cut == pytest.approx(8333.3333, abs=1e-3)
        assert t.fill == pytest.approx(8333.3333, abs=1e-3)
        assert t.net == pytest.approx(0.0, abs=1e-9)

    def test_areas_and_depths(self, result):
        t = result.totals
        assert t.area == pytest.approx(10000)
        assert t.area_cut == pytest.approx(5000, abs=1e-6)
        assert t.area_fill == pytest.approx(5000, abs=1e-6)
        assert t.max_depth_cut == pytest.approx(5.0, abs=1e-9)
        assert t.max_depth_fill == pytest.approx(5.0, abs=1e-9)

    def test_facet_sum_equals_total(self, result):
        assert sum(f.cut for f in result.facets) == pytest.approx(
            result.totals.cut, rel=1e-9)
        assert sum(f.fill for f in result.facets) == pytest.approx(
            result.totals.fill, rel=1e-9)
        assert sum(f.area for f in result.facets) == pytest.approx(
            result.totals.area, rel=1e-6)

    def test_facet_drilldown_fields(self, result):
        f = result.facets[0]
        assert len(f.vertices) == 3
        assert len(f.z_ground) == 3 and len(f.z_design) == 3
        assert all(math.isfinite(v) for v in f.dz)
        assert f.source_ground_tri is not None

    def test_no_issues(self, result):
        assert result.issues == []


class TestHoleCase:
    def test_hole_deductions(self):
        r = compute(case_hole(), ComputeOptions(section_spacing=100))
        assert r.totals.area == pytest.approx(9800)       # 10000-200
        assert r.totals.cut == pytest.approx(8275.0, abs=1e-3)
        assert r.totals.fill == pytest.approx(8325.0, abs=1e-3)

    def test_hole_geometry_returned(self):
        r = compute(case_hole())
        assert len(r.holes) == 1


class TestGapCase:
    def test_gap_not_extrapolated(self):
        r = compute(case_gap(), ComputeOptions(section_spacing=100))
        t = r.totals
        assert t.area == pytest.approx(9400)               # 10000-600
        assert t.cut == pytest.approx(8266.6667, abs=1e-2)
        assert t.fill == pytest.approx(8116.6667, abs=1e-2)

    def test_nodata_returned(self):
        r = compute(case_gap())
        assert len(r.no_data) == 1


class TestQCCase:
    def test_issues_listed(self):
        r = compute(case_qc())
        kinds = {i.kind for i in r.issues}
        assert "duplicate_exact" in kinds
        assert "duplicate_conflict" in kinds
        assert "outside" in kinds
        conflict = next(i for i in r.issues
                        if i.kind == "duplicate_conflict")
        assert conflict.severity == "error"


class TestGridConvergence:
    def test_finer_grid_closer_to_tin(self):
        r = compute(case_rolling(), ComputeOptions(section_spacing=100))
        by_size = {g.size: g for g in r.grid_compare}
        # 同一口径下，10m 网格相对 TIN 的偏差不劣于 40m 网格（通常更优）
        assert abs(by_size[10].rel_cut_pct) <= abs(by_size[40].rel_cut_pct) + 2
