"""运行配置。

存储默认落盘到 data/ 目录；设置 DATABASE_URL（postgresql://...）后自动切换
PostGIS 仓库。垂直基准必须由调用方显式声明，本系统不做静默假定。
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("EARTHWORK_DATA_DIR", BASE_DIR / "data"))

# postgresql://user:pass@host:port/dbname?sslmode=disable
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip() or None

# 三角网裁剪安全余量：三角片中点必须严格位于边界内（含孔洞收缩）。
# Shapely 2.0 prepared contains 已足够快，该值仅用于退化判定日志。
TRIANGLE_INSIDE_EPSILON = 1e-9

CORS_ORIGINS = os.environ.get(
    "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",")
