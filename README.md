# 场地挖填量 TIN 计算系统（Vue 3 + Three.js / FastAPI + SciPy + Shapely / PostGIS）

对**原地面**与**设计地面**在限定边界内分别构建 TIN，挖方、填方**分别精确积分**，
并以三维曲面、断面、三角片下钻展示。结果定位为**软件算例**，不替代现场计量认定。

## 工程纪律（本系统如何落实）

1. **统一坐标与高程基准**：两组数据分别声明 EPSG 与高程基准；不同 EPSG 经
   pyproj 重投影到同一米制投影坐标系（经纬度坐标系直接拒绝积分）；高程基准
   不一致时**必须显式提供 `vertical_offset`**，系统不假定基准差为零。
2. **边界外不外推**：TIN 逐三角片判定“质心在域内 且 三角片 ⊆ 边界（含孔洞）”，
   越界片一律拒绝。外边界与孔洞环顶点作为约束点注入，高程仅在实测点凸包内
   **线性内插**并显式标注（`__boundary__`），凸包外不赋值。
3. **重复点 / 退化三角网逐项列出**：完全重复点、同平面高程冲突（暂取均值、
   标注待复核）、边界外点、NaN/Inf、零面积/狭长片全部进问题清单，不静默删除。
4. **挖、填分别积分**：以两 TIN 相交三角片为单元，插入高差零线后对仿射高差
   精确积分；输出挖方、填方、净体积（仅参考）、总搬运量。净体积为零也不会
   掩盖同时存在的挖填（坡地算例净值 0，但挖、填各 2500 m³）。
5. **局部缺测不补不外推**：用最大边长 + 外接圆半径（α-shape）剔除跨越无数据
   区的长条片，报告内部缺测面积，断面在缺测段断线。
6. **网格精度可比较**：同时给出 TIN 精确积分与多档规则网格（中点法）结果及
   偏差，网格越细越趋近精确值。
7. **可追溯下钻**：总量 → 地面三角片 → 两 TIN 相交并按零线分割的最小积分单元
   （面积、挖、填、均高差、平面位置）；断面给出逐桩号高程与挖填断面面积。
8. **算例声明**：所有输出附“软件算例，不替代现场实测、监理与造价计量认定”。

## 内置算例

| key | 内容 | 手算结果 |
|---|---|---|
| `slope` | 100×100，原地面 2% 坡 z=0.02x，设计 z=1.0 | 挖 2500 / 填 2500 m³，净 0，断面挖填各 25 m² |
| `hole` | 中央 20×20 孔洞（既有构筑物，不计量） | 挖 2480 / 填 2480 m³，面积 9600 m² |
| `missing` | 10 m 网格、中央 40×40 局部缺测 | 报告内部缺测约 1400 m²（四角半格为三点实测合法内插），断面断线 |
| `dirty` | 完全重复/高程冲突/越界/NaN | 问题清单逐条列出 |

## 快速开始

```bash
# 后端（默认 JSON 落盘；设置 DATABASE_URL 后自动切换 PostGIS）
cd backend
python3 -m pip install -r requirements.txt   # 含可选 pyproj（不同 EPSG 重投影需要）
python3 -m uvicorn app.main:app --reload --port 8011

# 前端
cd frontend
npm install
npm run dev        # http://localhost:5173 ，/api 代理到 8011
```

测试：

```bash
cd backend && python3 -m pytest -q
```

## 启用 PostgreSQL/PostGIS

```bash
docker compose up -d db
export DATABASE_URL="postgresql://earthwork:earthwork@localhost:5432/earthwork"
# 重启后端即自动执行 backend/app/db/schema.sql（CREATE EXTENSION postgis …）
```

未配置数据库时自动退化为 `backend/data/schemes.json` 落盘，接口不变。
表结构：`survey_dataset` / `survey_point(POINTZ)` /
`earthwork_scheme(MULTIPOLYGON, params, result)`。

## 主要接口

- `GET  /api/cases`、`GET /api/cases/{key}`：算例与完整请求体
- `POST /api/cases/{key}/compute`：计算内置算例（返回理论值对照）
- `POST /api/compute`：提交自定义方案（可指定 `sections`、`grid_spacings`、
  `max_triangle_edge`、`max_circumradius`）
- `GET  /api/schemes`、`GET /api/schemes/{id}`、
  `POST /api/schemes/{id}/recompute`：方案存取与复算

设计面支持 `{"kind":"plane","a","b","c"}` 或 `{"kind":"points",...}`
（设计点 TIN，同样做基准统一与质检）。

## 算法说明

- TIN：`scipy.spatial.Delaunay`（QJ 扰动 + Steiner 边界约束点），
  Shapely 做多边形裁剪、孔洞扣除、未覆盖区统计、STRtree 空间索引。
- 积分：两 TIN 三角片 Shapely 求交 → Sutherland–Hodgman 按高差零线裁剪 →
  耳切/扇形三角化 → 仿射函数在三角形上的精确积分 `A·(f1+f2+f3)/3`。
- 断面：断面线按步长在 TIN 上重心坐标线性插值，缺测/域外返回空值断线，
  梯形法分段积分挖填断面面积。
- 前端：Three.js 非索引三角片平面着色（挖红/填蓝）、设计面对照面、
  挖填棱柱体、缺测区灰面、测点/约束点区分；Canvas 2D 断面图。

## 免责声明

所有算例与计算结果仅用于设计、方案比选与软件验证。正式工程量应以现场
实测成果、监理确认及合同约定的计量规则为准。
