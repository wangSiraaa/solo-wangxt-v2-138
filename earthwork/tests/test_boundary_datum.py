"""防外推 / 边界孔洞 / 基准专项测试。"""
import numpy as np
import pytest

from app.models import ComputeOptions, Datum, Point, Project, Ring
from app.engine import compute


def _pts(xs, ys, zfunc, surface):
    return [Point(x=float(x), y=float(y), z=float(zfunc(x, y)), surface=surface)
            for x in xs for y in ys]


class TestNoExtrapolation:
    def _project(self):
        # 原地面覆盖 100x100；设计面只有中央 40x40 有点
        g = _pts(np.arange(0, 101, 20), np.arange(0, 101, 20),
                 lambda x, y: 5.0, "ground")
        d = _pts(np.arange(30, 71, 10), np.arange(30, 71, 10),
                 lambda x, y: 0.0, "design")
        boundary = [Ring(coords=[(0, 0), (100, 0), (100, 100), (0, 100)])]
        return Project(name="设计面只覆盖中央区", points=g + d,
                       boundary=boundary,
                       datum=Datum(horizontal_crs="EPSG:4547",
                                   vertical_datum="1985国家高程基准"))

    def test_area_limited_to_design_hull(self):
        r = compute(self._project(), ComputeOptions(section_spacing=100))
        # 设计面凸包 40x40=1600；边界虽声明 10000，也不得计算边界外区域
        assert r.totals.area == pytest.approx(1600, abs=2)
        assert r.totals.cut == pytest.approx(5 * 1600, rel=0.02)
        assert r.totals.fill == 0
        # 原地面有 8400 m² 在设计面覆盖外
        assert r.uncovered_area == pytest.approx(8400, rel=0.02)

    def test_ground_with_gap_uncovered_too(self):
        # 设计覆盖全域，原地面内部缺测一块：内部删点不改变凸包，Delaunay 会
        # 跨过空区，因此必须显式圈 no_data 或由 QC 大片警告提示。
        # 这里验证显式圈出缺测区后该区域不参与计算、不外推。
        g = _pts(np.arange(0, 101, 10), np.arange(0, 101, 10),
                 lambda x, y: 3.0, "ground")
        g = [p for p in g if not (40 < p.x < 60 and 40 < p.y < 60)]
        d = _pts(np.arange(0, 101, 20), np.arange(0, 101, 20),
                 lambda x, y: 0.0, "design")
        boundary = [Ring(coords=[(0, 0), (100, 0), (100, 100), (0, 100)])]
        no_data = [[(40, 40), (60, 40), (60, 60), (40, 60)]]
        proj = Project(name="原地面中央缺测", points=g + d,
                       boundary=boundary, no_data=no_data)
        r = compute(proj, ComputeOptions(section_spacing=100))
        assert r.totals.area == pytest.approx(9600, rel=0.01)
        assert r.totals.cut == pytest.approx(3 * 9600, rel=0.02)
        assert r.totals.fill == 0

    def test_interior_gap_flagged_by_qc_when_not_circled(self):
        # 不圈缺测区时，跨空区的瘦长大片必须在 QC 中警告（提醒补测/圈范围）。
        # 构造：上下两排点、中间一条宽空带，Delaunay 必然拉出瘦长大片。
        def ring(n):
            return ([Point(x=float(x), y=0.0, z=3.0, surface="ground")
                     for x in np.linspace(0, 100, n)]
                    + [Point(x=float(x), y=100.0, z=3.0, surface="ground")
                       for x in np.linspace(0, 100, n)])
        g = ring(11)
        d = _pts(np.arange(0, 101, 25), np.arange(0, 101, 25),
                 lambda x, y: 0.0, "design")
        r = compute(Project(name="未圈缺测", points=g + d),
                    ComputeOptions(section_spacing=100, gap_max_area=400))
        assert any(i.kind == "oversized" for i in r.issues)


class TestDatum:
    def test_conflicting_crs_rejected_by_api(self):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        proj = Project(
            name="基准不一致",
            points=[Point(x=0, y=0, z=0, surface="ground"),
                    Point(x=10, y=0, z=1, surface="ground"),
                    Point(x=0, y=10, z=1, surface="ground"),
                    Point(x=0, y=0, z=0, surface="design"),
                    Point(x=10, y=0, z=0, surface="design"),
                    Point(x=0, y=10, z=0, surface="design")],
            datum=Datum(horizontal_crs="EPSG:4547", vertical_datum="1985"),
            design_datum=Datum(horizontal_crs="EPSG:32650", vertical_datum="1985"))
        resp = client.post("/api/compute", json={"project": proj.model_dump()})
        assert resp.status_code == 422
        assert "坐标系不一致" in resp.json()["detail"]

    def test_vertical_datum_conflict_rejected(self):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        proj = Project(
            name="高程基准不一致",
            points=[Point(x=0, y=0, z=0, surface="ground"),
                    Point(x=10, y=0, z=1, surface="ground"),
                    Point(x=0, y=10, z=1, surface="ground"),
                    Point(x=0, y=0, z=0, surface="design"),
                    Point(x=10, y=0, z=0, surface="design"),
                    Point(x=0, y=10, z=0, surface="design")],
            datum=Datum(horizontal_crs="EPSG:4547", vertical_datum="1985国家高程基准"),
            design_datum=Datum(horizontal_crs="EPSG:4547",
                               vertical_datum="地方假定高程"))
        resp = client.post("/api/compute", json={"project": proj.model_dump()})
        assert resp.status_code == 422
        assert "高程基准不一致" in resp.json()["detail"]
