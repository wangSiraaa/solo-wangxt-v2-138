"""方案与数据集仓库：PostGIS 优先，未配置 DATABASE_URL 时落盘 JSON。

两层接口一致，便于本地无数据库环境演示与测试。落盘文件存于
config.DATA_DIR（默认 backend/data）。
"""
from __future__ import annotations

import json
import time
import threading
from pathlib import Path
from typing import Optional

from .. import config


class Repository:
    def save_scheme(self, name: str, payload: dict, result: dict) -> int: ...
    def save_dataset(self, name, role, epsg, vertical_datum, points): ...
    def load_scheme(self, scheme_id: int) -> Optional[dict]: ...
    def list_schemes(self, limit: int = 50) -> list[dict]: ...
    def health(self) -> dict: ...


class JsonRepository(Repository):
    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "schemes.json"
        self._lock = threading.Lock()
        if not self.path.exists():
            self.path.write_text("[]", encoding="utf-8")

    def _all(self) -> list:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def save_scheme(self, name, payload, result) -> int:
        with self._lock:
            rows = self._all()
            sid = max((r["id"] for r in rows), default=0) + 1
            rows.append({
                "id": sid, "name": name,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "payload": payload, "result": result,
                "backend": "json-file",
            })
            self.path.write_text(
                json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        return sid

    def load_scheme(self, scheme_id):
        return next((r for r in self._all() if r["id"] == scheme_id), None)

    def save_dataset(self, name, role, epsg, vertical_datum, points):
        return None  # 落盘模式不单独建数据集（点随方案 JSON 保存）

    def list_schemes(self, limit=50):
        return [{
            "id": r["id"], "name": r["name"],
            "created_at": r["created_at"],
            "volume": r.get("result", {}).get("volume", {}),
            "backend": r.get("backend", "json-file"),
        } for r in reversed(self._all()[-limit:])]

    def health(self):
        return {"storage": "json-file", "path": str(self.path)}


class PostgresRepository(Repository):
    def __init__(self, url: str):
        import psycopg2
        self._psycopg2 = psycopg2
        self.url = url

    def _conn(self):
        conn = self._psycopg2.connect(self.url)
        conn.autocommit = True
        return conn

    def init_schema(self):
        from pathlib import Path
        sql = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(sql)

    def save_scheme(self, name, payload, result) -> int:
        import json as _json
        geojson = payload["boundary"]
        epsg = int(payload.get("target_epsg", 0))
        ground_id = self.save_dataset(
            f"{name}-原地面", "ground", epsg,
            payload.get("target_vertical_datum", "local"),
            payload.get("ground", {}).get("points", []))
        design_id = None
        if payload.get("design", {}).get("kind") == "points":
            design_id = self.save_dataset(
                f"{name}-设计面", "design",
                int(payload["design"].get("epsg", epsg)),
                payload["design"].get("vertical_datum", "local"),
                payload["design"].get("points", []))
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO earthwork_scheme
                    (name, target_epsg, boundary, params, result,
                     ground_dataset, design_dataset)
                VALUES (%s, %s,
                        ST_SetSRID(ST_Multi(ST_GeomFromGeoJSON(%s)), %s),
                        %s::jsonb, %s::jsonb, %s, %s)
                RETURNING id
                """,
                (name, epsg, _json.dumps(geojson), epsg,
                 _json.dumps(payload, ensure_ascii=False),
                 _json.dumps(result, ensure_ascii=False),
                 ground_id, design_id),
            )
            return int(cur.fetchone()[0])

    def save_dataset(self, name, role, epsg, vertical_datum, points) -> Optional[int]:
        """高程点入库：ST_MakePoint(x,y,z) + 显式 SRID。"""
        if not points:
            return None
        from psycopg2.extras import execute_values
        rows = [(p.get("code"), float(p["x"]), float(p["y"]), float(p["z"]))
                if p.get("code") is not None
                else (str(p.get("id")) if p.get("id") is not None else None,
                      float(p["x"]), float(p["y"]), float(p["z"]))
                for p in points
                if all(k in p for k in ("x", "y", "z"))]
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO survey_dataset (name, role, epsg, vertical_datum)
                   VALUES (%s, %s, %s, %s) RETURNING id""",
                (name, role, int(epsg), vertical_datum),
            )
            ds_id = int(cur.fetchone()[0])
            execute_values(
                cur,
                """INSERT INTO survey_point (dataset_id, point_code, geom)
                   VALUES %s""",
                rows, page_size=1000,
                template=(
                    f"({ds_id}, %s, "
                    f"ST_SetSRID(ST_MakePoint(%s, %s, %s), {int(epsg)}))"
                ),
            )
        return ds_id

    def load_scheme(self, scheme_id):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT id, name, created_at, params, result FROM earthwork_scheme
                   WHERE id = %s""", (scheme_id,))
            row = cur.fetchone()
        if not row:
            return None
        return {
            "id": row[0], "name": row[1],
            "created_at": row[2].isoformat() if row[2] else None,
            "payload": row[3], "result": row[4], "backend": "postgis",
        }

    def list_schemes(self, limit=50):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT id, name, created_at, result
                   FROM earthwork_scheme ORDER BY id DESC LIMIT %s""",
                (limit,))
            rows = cur.fetchall()
        return [{
            "id": r[0], "name": r[1],
            "created_at": r[2].isoformat() if r[2] else None,
            "volume": (r[3] or {}).get("volume", {}),
            "backend": "postgis",
        } for r in rows]

    def health(self):
        try:
            with self._conn() as conn, conn.cursor() as cur:
                cur.execute("SELECT PostGIS_version()")
                ver = cur.fetchone()[0]
            return {"storage": "postgis", "postgis": ver, "status": "ok"}
        except Exception as exc:
            return {"storage": "postgis", "status": "error", "error": str(exc)}


_repo: Optional[Repository] = None


def get_repo() -> Repository:
    global _repo
    if _repo is not None:
        return _repo
    if config.DATABASE_URL:
        repo = PostgresRepository(config.DATABASE_URL)
        try:
            repo.init_schema()
        except Exception:
            # 数据库不可用时不阻断服务，退回落盘并在 health 报告
            repo = JsonRepository(config.DATA_DIR)
    else:
        repo = JsonRepository(config.DATA_DIR)
    _repo = repo
    return repo
