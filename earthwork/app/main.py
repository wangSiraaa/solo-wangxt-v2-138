"""FastAPI 入口。

端点：
  GET  /api/health
  GET  /api/cases                      内置算例列表
  GET  /api/cases/{name}               取算例数据
  POST /api/compute                    直接提交方案计算（结果含三角片/断面明细）
  POST /api/projects                   保存方案
  GET  /api/projects                   方案列表
  GET  /api/projects/{pid}             取方案
  POST /api/projects/{pid}/compute     对已保存方案计算并存档
  GET  /api/projects/{pid}/runs        历史计算口径与总量
  GET  /api/runs/{rid}                 完整历史结果（含三角片，供追溯）

所有计算错误（基准不一致、点矛盾等）以 422 返回，不静默吞掉。
"""
from __future__ import annotations

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .cases import ALL_CASES
from .crs import transform_xy
from .db.store import get_store
from .engine import compute
from .models import ComputeOptions, Point, Project


class BlockingError(Exception):
    """基准不一致等使计算结果无效的问题，返回 422 拒绝计算。"""


def _assert_datum_consistent(project: Project):
    d1, d2 = project.datum, project.design_datum
    if d2 is None:
        return
    if (d1.horizontal_crs and d2.horizontal_crs
            and d1.horizontal_crs != d2.horizontal_crs):
        raise BlockingError(
            f"平面坐标系不一致：原地面 {d1.horizontal_crs} vs 设计面 "
            f"{d2.horizontal_crs}。必须先用 pyproj 转换统一后再计算，"
            f"禁止在不同坐标系上直接建网。")
    if (d1.vertical_datum and d2.vertical_datum
            and d1.vertical_datum != d2.vertical_datum):
        raise BlockingError(
            f"高程基准不一致：原地面 {d1.vertical_datum} vs 设计面 "
            f"{d2.vertical_datum}。必须经水准联测/拟合作高程改算后再计算，"
            f"软件不猜测基准间偏移。")

app = FastAPI(title="土方挖填量计算系统（TIN/断面/网格）", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_store = None


def store():
    global _store
    if _store is None:
        _store = get_store()
    return _store


class ComputeRequest(BaseModel):
    project: Project
    options: ComputeOptions | None = None
    save: bool = False


@app.get("/api/health")
def health():
    s = store()
    return {"status": "ok", "storage_backend": getattr(s, "backend", "?")}


@app.get("/api/cases")
def list_cases():
    return [{"key": k, "name": v().name,
             "n_points": len(v().points),
             "n_holes": len(v().holes),
             "n_no_data": len(v().no_data)}
            for k, v in ALL_CASES.items()]


@app.get("/api/cases/{name}")
def get_case(name: str):
    if name not in ALL_CASES:
        raise HTTPException(404, f"未知算例 {name}")
    return ALL_CASES[name]()


@app.post("/api/compute")
def do_compute(req: ComputeRequest):
    try:
        _assert_datum_consistent(req.project)
        result = compute(req.project, req.options)
    except (ValueError, BlockingError) as e:
        raise HTTPException(422, str(e))
    rid = None
    if req.save:
        pid = store().save_project(req.project)
        rid = store().save_run(pid, result, req.options or ComputeOptions())
        return {"project_id": pid, "run_id": rid, "result": result}
    return {"result": result}


@app.post("/api/projects")
def create_project(project: Project):
    pid = store().save_project(project)
    return {"id": pid}


@app.get("/api/projects")
def projects():
    return store().list_projects()


@app.get("/api/projects/{pid}")
def get_project(pid: int):
    try:
        return store().load_project(pid)
    except KeyError:
        raise HTTPException(404, f"方案 {pid} 不存在")


@app.post("/api/projects/{pid}/compute")
def compute_saved(pid: int, options: ComputeOptions | None = None):
    try:
        project = store().load_project(pid)
    except KeyError:
        raise HTTPException(404, f"方案 {pid} 不存在")
    try:
        result = compute(project, options)
    except ValueError as e:
        raise HTTPException(422, str(e))
    rid = store().save_run(pid, result, options or ComputeOptions())
    return {"run_id": rid, "result": result}


@app.get("/api/projects/{pid}/runs")
def runs(pid: int):
    return store().list_runs(pid)


@app.get("/api/runs/{rid}")
def get_run(rid: int):
    rec = store().get_run(rid)
    if not rec:
        raise HTTPException(404, f"运行 {rid} 不存在")
    return rec


@app.post("/api/parse-xyz")
async def parse_xyz(file: UploadFile = File(...),
                    surface: str = "ground",
                    source_crs: str | None = None,
                    target_crs: str | None = None):
    """解析 XYZ/CSV 文本点（x,y,z 每行一个，逗号/空白/Tab 分隔）。

    给定 source_crs、target_crs 时用 pyproj 统一平面坐标；高程不做猜测性改算。
    重复点检测留给 /api/compute 的 QC，这里只解析与坐标转换。
    """
    if surface not in ("ground", "design"):
        raise HTTPException(422, "surface 必须是 ground 或 design")
    text = (await file.read()).decode("utf-8-sig", errors="replace")
    points, bad = [], 0
    for ln, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith(("#", "//")):
            continue
        parts = [p for p in line.replace(",", " ").replace("\t", " ").split()]
        if len(parts) < 3:
            bad += 1
            continue
        try:
            x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
        except ValueError:
            bad += 1
            continue
        code = parts[3] if len(parts) > 3 else None
        points.append(Point(x=x, y=y, z=z, surface=surface, code=code))
    if len(points) < 3:
        raise HTTPException(422, f"有效点不足 3 个（{bad} 行无法解析），无法构建 TIN")
    if source_crs and target_crs and source_crs != target_crs:
        try:
            points = transform_xy(points, source_crs, target_crs)
        except Exception as e:
            raise HTTPException(422, f"坐标转换失败：{e}")
    return {"surface": surface, "n_points": len(points),
            "bad_lines": bad, "points": points}
