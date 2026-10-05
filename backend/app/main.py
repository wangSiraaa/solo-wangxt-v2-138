"""FastAPI 入口：算例、计算、方案存取、下钻、健康检查。"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import config
from .geo.engine import run_scheme
from .geo.fixtures import ALL_CASES
from .geo.datum import DatumError
from .geo.boundary import BoundaryError
from .db.repository import get_repo
from .schemas import SchemeRequest

app = FastAPI(
    title="场地挖填量 TIN 计算服务",
    version="1.0.0",
    description=(
        "限定边界 TIN（SciPy Delaunay + Shapely）挖填分别积分；"
        "挖、填分量独立报告，不用净体积掩盖；结果为软件算例，"
        "不替代现场计量认定。"
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

DISCLAIMER = (
    "本结果为软件算例，仅供设计与方案比选；正式工程量以现场实测、"
    "监理与造价计量认定为准。"
)


@app.get("/")
def root():
    return {"service": "earthwork-tin", "disclaimer": DISCLAIMER,
            "docs": "/docs"}


@app.get("/api/health")
def health():
    return {"storage": get_repo().health(), "disclaimer": DISCLAIMER}


@app.get("/api/cases")
def list_cases():
    return [
        {"key": k, "name": fn()["name"],
         "expected": fn().get("expected"),
         "expected_note": fn().get("expected_note")}
        for k, fn in ALL_CASES.items()
    ]


@app.get("/api/cases/{key}")
def get_case(key: str):
    if key not in ALL_CASES:
        raise HTTPException(404, f"算例 {key} 不存在")
    return ALL_CASES[key]()


def _compute(payload: dict) -> dict:
    try:
        result = run_scheme(payload)
    except DatumError as exc:
        raise HTTPException(422, f"基准不统一：{exc}")
    except BoundaryError as exc:
        raise HTTPException(422, f"边界无效：{exc}")
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    result["disclaimer"] = DISCLAIMER
    return result


@app.post("/api/compute")
def compute(req: SchemeRequest):
    payload = req.model_dump(exclude_none=True)
    payload.pop("name", None)
    do_persist = payload.pop("persist", True)
    result = _compute(payload)
    if do_persist:
        sid = get_repo().save_scheme(req.name or "未命名方案", payload, result)
        result["scheme_id"] = sid
    return result


@app.post("/api/cases/{key}/compute")
def compute_case(key: str):
    if key not in ALL_CASES:
        raise HTTPException(404, f"算例 {key} 不存在")
    case = ALL_CASES[key]()
    result = _compute(case["payload"])
    result["case"] = key
    result["case_name"] = case["name"]
    result["expected"] = case.get("expected")
    result["expected_note"] = case.get("expected_note")
    return result


@app.get("/api/schemes")
def schemes():
    return get_repo().list_schemes()


@app.get("/api/schemes/{scheme_id}")
def get_scheme(scheme_id: int):
    row = get_repo().load_scheme(scheme_id)
    if not row:
        raise HTTPException(404, "方案不存在")
    return row


@app.post("/api/schemes/{scheme_id}/recompute")
def recompute(scheme_id: int):
    row = get_repo().load_scheme(scheme_id)
    if not row:
        raise HTTPException(404, "方案不存在")
    return _compute(row["payload"])


@app.exception_handler(Exception)
def unhandled(_request, exc):  # 兜底，避免前端拿到 HTML 错误页
    return JSONResponse(status_code=500,
                        content={"error": str(exc), "type": type(exc).__name__})
