-- 土方挖填计算系统 —— PostgreSQL/PostGIS 表结构
-- 要求 PostGIS >= 3.x；高程点坐标统一存工程平面坐标(米)，
-- 坐标系 EPSG 记录在 projects.horizontal_crs，禁止混用坐标系直接入库。

CREATE EXTENSION IF NOT EXISTS postgis;

-- 方案 / 工程
CREATE TABLE IF NOT EXISTS projects (
    id               BIGSERIAL PRIMARY KEY,
    name             TEXT NOT NULL,
    horizontal_crs   TEXT,                       -- 如 EPSG:4547
    vertical_datum   TEXT,                       -- 如 1985国家高程基准
    boundary         geometry(MultiPolygon, 0), -- 边界(含洞)，0=工程坐标未注册SRID时按业务码解释
    no_data          geometry(MultiPolygon, 0),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    note             TEXT
);

-- 高程点：原地面 / 设计面分开，surface 字段区分
CREATE TABLE IF NOT EXISTS elevation_points (
    id        BIGSERIAL PRIMARY KEY,
    project_id BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    surface   TEXT NOT NULL CHECK (surface IN ('ground', 'design')),
    code      TEXT,
    geom      geometry(Point, 0) NOT NULL,       -- XYZ 点，z 为统一高程基准下高程
    z         DOUBLE PRECISION NOT NULL,
    CONSTRAINT chk_z_finite CHECK (z = z AND z BETWEEN -1e6 AND 1e6)
);
CREATE INDEX IF NOT EXISTS idx_points_project_surface
    ON elevation_points (project_id, surface);
CREATE INDEX IF NOT EXISTS idx_points_geom
    ON elevation_points USING gist (geom);

-- 重复点检查视图：同面、同坐标、高程不一致（数据矛盾）
CREATE OR REPLACE VIEW v_conflicting_points AS
SELECT a.project_id, a.surface, a.id AS id_a, b.id AS id_b,
       ST_X(a.geom) AS x, ST_Y(a.geom) AS y, a.z AS za, b.z AS zb
FROM elevation_points a
JOIN elevation_points b
  ON a.project_id = b.project_id AND a.surface = b.surface AND a.id < b.id
WHERE ST_Intersects(ST_Force2D(a.geom), ST_Force2D(b.geom))
  AND abs(a.z - b.z) > 0.001;

-- 计算运行记录（每次提交计算留存口径参数，结果 JSON 存档）
CREATE TABLE IF NOT EXISTS compute_runs (
    id           BIGSERIAL PRIMARY KEY,
    project_id   BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    ran_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    grid_size    DOUBLE PRECISION NOT NULL,
    section_spacing DOUBLE PRECISION NOT NULL,
    cut_m3       DOUBLE PRECISION NOT NULL,
    fill_m3      DOUBLE PRECISION NOT NULL,
    net_m3       DOUBLE PRECISION NOT NULL,
    area_m2      DOUBLE PRECISION NOT NULL,
    result_json  JSONB NOT NULL,
    confirmed_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_project ON compute_runs (project_id, ran_at);
