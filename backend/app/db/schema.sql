"""PostGIS schema。在 PostgreSQL 中执行（需先 CREATE EXTENSION postgis）。

存储内容：
- survey_dataset 高程点数据集（原地面/设计面），点用 geometry(POINTZ, :srid)
- earthwork_scheme  计算方案（边界、参数、结果 JSON）
- scheme_dataset_rel 方案与数据集关联（方案含原地面 + 设计面两份数据）
"""

SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS postgis;

-- 高程点数据集 -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS survey_dataset (
    id              BIGSERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('ground','design')),
    epsg            INTEGER NOT NULL,
    vertical_datum  TEXT NOT NULL DEFAULT 'local',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS survey_point (
    id          BIGSERIAL PRIMARY KEY,
    dataset_id  BIGINT NOT NULL REFERENCES survey_dataset(id) ON DELETE CASCADE,
    point_code  TEXT,
    geom        geometry(POINTZ) NOT NULL,
    meta        JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_survey_point_dataset
    ON survey_point(dataset_id);
CREATE INDEX IF NOT EXISTS idx_survey_point_geom
    ON survey_point USING GIST (geom);
-- 同一数据集内禁止完全重复的平面位置（由应用质检配合；DB 层兜底）
CREATE UNIQUE INDEX IF NOT EXISTS uq_survey_point_xy
    ON survey_point(dataset_id,
                    ST_SnapToGrid(ST_X(geom), 0.001),
                    ST_SnapToGrid(ST_Y(geom), 0.001));

-- 计算方案 -----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS earthwork_scheme (
    id              BIGSERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    target_epsg     INTEGER NOT NULL,
    boundary        geometry(MULTIPOLYGON) NOT NULL,
    params          JSONB NOT NULL DEFAULT '{}'::jsonb,
    result          JSONB,
    ground_dataset  BIGINT REFERENCES survey_dataset(id),
    design_dataset  BIGINT REFERENCES survey_dataset(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    disclaimer      TEXT NOT NULL DEFAULT
        '软件算例结果，仅供设计与方案比选，不替代现场计量与监理认定。'
);
CREATE INDEX IF NOT EXISTS idx_earthwork_scheme_geom
    ON earthwork_scheme USING GIST (boundary);
"""
