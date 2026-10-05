"""存储层：优先 PostgreSQL/PostGIS；无连接时自动回退到本地 JSON 文件。

两种后端实现同一接口，API 无需感知：
    save_project(project) -> int
    load_project(pid) -> Project
    list_projects() -> [dict]
    save_run(pid, result, options) -> int
    list_runs(pid) -> [dict]
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

from ..models import ComputeOptions, Point, Project, Ring

DATA_DIR = Path(os.environ.get("EW_DATA_DIR", "/workspace/earthwork/data"))
PG_DSN = os.environ.get("EW_PG_DSN", "")  # 设置即尝试 Postgres


# ---------------- 内存 / JSON 回退后端 ----------------
class JsonStore:
    def __init__(self, root: Path = DATA_DIR):
        root.mkdir(parents=True, exist_ok=True)
        self.projects_f = root / "projects.json"
        self.runs_f = root / "runs.json"
        self._projects = self._load(self.projects_f, {})
        self._runs = self._load(self.runs_f, {})

    @staticmethod
    def _load(f: Path, default):
        return json.loads(f.read_text("utf-8")) if f.exists() else default

    def _flush(self):
        self.projects_f.write_text(
            json.dumps(self._projects, ensure_ascii=False, indent=1), "utf-8")
        self.runs_f.write_text(
            json.dumps(self._runs, ensure_ascii=False, indent=1), "utf-8")

    def save_project(self, project: Project) -> int:
        pid = int(max((int(k) for k in self._projects), default=0)) + 1
        self._projects[str(pid)] = project.model_dump()
        self._projects[str(pid)]["id"] = pid
        self._flush()
        return pid

    def load_project(self, pid: int) -> Project:
        if str(pid) not in self._projects:
            raise KeyError(pid)
        data = dict(self._projects[str(pid)])
        data.pop("id", None)
        return Project(**data)

    def list_projects(self) -> list[dict]:
        return [{"id": int(k), "name": v["name"],
                 "datum": v.get("datum"),
                 "created_at": v.get("created_at")}
                for k, v in self._projects.items()]

    def save_run(self, pid: int, result, options: ComputeOptions) -> int:
        rid = int(max((int(k) for k in self._runs), default=0)) + 1
        rec = {
            "id": rid, "project_id": pid, "ran_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "grid_size": options.grid_size,
            "section_spacing": options.section_spacing,
            "cut_m3": result.totals.cut, "fill_m3": result.totals.fill,
            "net_m3": result.totals.net, "area_m2": result.totals.area,
            "result_json": json.loads(result.model_dump_json()),
        }
        self._runs.setdefault(str(pid), []).append(rec)
        self._flush()
        return rid

    def list_runs(self, pid: int) -> list[dict]:
        out = []
        for rec in self._runs.get(str(pid), []):
            out.append({k: v for k, v in rec.items() if k != "result_json"})
        return out

    def get_run(self, rid: int) -> Optional[dict]:
        for recs in self._runs.values():
            for rec in recs:
                if rec["id"] == rid:
                    return rec
        return None


# ---------------- Postgres/PostGIS 后端 ----------------
class PgStore:
    def __init__(self, dsn: str):
        import psycopg
        self._psycopg = psycopg
        self.dsn = dsn
        with self._conn() as conn:
            with conn.cursor() as cur:
                schema = Path(__file__).with_name("schema.sql").read_text("utf-8")
                cur.execute(schema)

    def _conn(self):
        return self._psycopg.connect(self.dsn, autocommit=True)

    def save_project(self, project: Project) -> int:
        from shapely.geometry import Polygon
        from shapely import wkt
        boundary = None
        if project.boundary:
            outer = project.boundary[0].coords
            holes = [r.coords for r in project.boundary[1:]]
            boundary = wkt.dumps(Polygon(outer, holes))
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO projects(name, horizontal_crs, vertical_datum, "
                    "boundary) VALUES (%s,%s,%s,"
                    "ST_GeomFromText(%s,0)) RETURNING id",
                    (project.name, project.datum.horizontal_crs,
                     project.datum.vertical_datum,
                     boundary or "MULTIPOLYGON EMPTY"))
                pid = cur.fetchone()[0]
                rows = [(pid, p.surface, p.code, p.x, p.y, p.z, p.z)
                        for p in project.points]
                cur.executemany(
                    "INSERT INTO elevation_points"
                    "(project_id,surface,code,geom,z) "
                    "VALUES (%s,%s,%s,ST_SetSRID(ST_MakePoint(%s,%s,%s),0),%s)",
                    rows)
        return pid

    def load_project(self, pid: int) -> Project:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT name, horizontal_crs, vertical_datum "
                            "FROM projects WHERE id=%s", (pid,))
                row = cur.fetchone()
                if not row:
                    raise KeyError(pid)
                name, hcrs, vd = row
                cur.execute(
                    "SELECT surface, code, ST_X(geom), ST_Y(geom), z "
                    "FROM elevation_points WHERE project_id=%s", (pid,))
                points = [Point(surface=r[0], code=r[1], x=r[2], y=r[3], z=r[4])
                          for r in cur.fetchall()]
        from ..models import Datum
        return Project(name=name, points=points,
                       datum=Datum(horizontal_crs=hcrs, vertical_datum=vd or ""))

    def list_projects(self) -> list[dict]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, name, horizontal_crs, vertical_datum, "
                            "created_at FROM projects ORDER BY id")
                return [{"id": r[0], "name": r[1],
                         "datum": {"horizontal_crs": r[2],
                                   "vertical_datum": r[3]},
                         "created_at": r[4].isoformat() if r[4] else None}
                        for r in cur.fetchall()]

    def save_run(self, pid: int, result, options: ComputeOptions) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO compute_runs(project_id,grid_size,"
                    "section_spacing,cut_m3,fill_m3,net_m3,area_m2,result_json) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb) RETURNING id",
                    (pid, options.grid_size, options.section_spacing,
                     result.totals.cut, result.totals.fill, result.totals.net,
                     result.totals.area, result.model_dump_json()))
                return cur.fetchone()[0]

    def list_runs(self, pid: int) -> list[dict]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, ran_at, grid_size, section_spacing, "
                            "cut_m3, fill_m3, net_m3, area_m2 "
                            "FROM compute_runs WHERE project_id=%s ORDER BY id",
                            (pid,))
                cols = [d.name for d in cur.description]
                return [dict(zip(cols, r)) for r in cur.fetchall()]

    def get_run(self, rid: int) -> Optional[dict]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT result_json FROM compute_runs WHERE id=%s",
                            (rid,))
                row = cur.fetchone()
                return row[0] if row else None


def get_store():
    """优先用 Postgres；连接失败回退 JSON 文件并记录后端类型。"""
    if PG_DSN:
        try:
            store = PgStore(PG_DSN)
            store.backend = "postgis"
            return store
        except Exception as e:  # 连不上时不致命，回退本地
            print(f"[store] Postgres 不可用({e})，回退 JSON 文件存储")
    store = JsonStore()
    store.backend = "json-file"
    return store
