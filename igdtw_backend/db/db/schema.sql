-- CHIRAAG — PostGIS schema
--
-- This file is the schema half of the deployment. It is generated to match
-- app/models/*.py exactly, i.e. it produces the same tables and indexes that
-- Base.metadata.create_all() would produce, with the same index names, so the
-- two paths never fight each other. Every statement is idempotent.
--
-- chiraag_data.sql is a DATA-ONLY dump (pg_dump --data-only): it contains no
-- CREATE TABLE and no CREATE INDEX, so it can only restore onto tables that
-- already exist. Restore order for a fresh database (Supabase included):
--
--     1. psql "$DATABASE_URL" -f db/db/schema.sql
--     2. psql "$DATABASE_URL" -f chiraag_data.sql
--
-- Run both from the igdtw_backend directory.
--
-- Supabase notes:
--   * Enable PostGIS once from Database -> Extensions in the dashboard. That
--     installs it into the "extensions" schema and makes the statement below a
--     no-op. Left here so a plain Postgres or the local postgis container works
--     from this file alone.
--   * The search_path line keeps the geometry type resolvable whether PostGIS
--     lives in "extensions" (Supabase) or "public" (local container). Postgres
--     ignores schemas in search_path that do not exist, so it is safe on both.

CREATE EXTENSION IF NOT EXISTS postgis;

SET search_path = public, extensions;


-- ---------------------------------------------------------------------------
-- 1. Scored road segments (graph edges)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS road_segments (
    id                       SERIAL NOT NULL,
    osm_id                   BIGINT NOT NULL,
    length_m                 FLOAT NOT NULL,
    dark_fraction            FLOAT,
    longest_gap_m            FLOAT,
    calibrated_lighting_prob FLOAT,
    observation_state        VARCHAR,
    geom                     geometry(LINESTRING, 4326) NOT NULL,
    created_at               TIMESTAMP WITH TIME ZONE DEFAULT now(),
    PRIMARY KEY (id)
);

-- dark_fraction, longest_gap_m, calibrated_lighting_prob and
-- observation_state are deliberately nullable with no database default. The
-- models apply their defaults in Python, and NULL is meaningful here: it means
-- "no evidence", which the routing code must never read as "not dark".

-- The bbox lookup in services/graph_builder.py depends on this one. Without it
-- every /api/v1/route request sequentially scans the whole table.
CREATE INDEX IF NOT EXISTS idx_road_segments_geom
    ON road_segments USING gist (geom);

CREATE INDEX IF NOT EXISTS ix_road_segments_osm_id
    ON road_segments (osm_id);

-- Redundant with the primary key, but create_all() emits it because the model
-- declares index=True on id. Kept so both paths produce an identical database.
CREATE INDEX IF NOT EXISTS ix_road_segments_id
    ON road_segments (id);


-- ---------------------------------------------------------------------------
-- 2. Streetlight detections
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS streetlights (
    id           SERIAL NOT NULL,
    mapillary_id VARCHAR,
    geom         geometry(POINT, 4326) NOT NULL,
    created_at   TIMESTAMP WITH TIME ZONE DEFAULT now(),
    PRIMARY KEY (id)
);

-- Used by the evidence endpoint's ST_DWithin light count.
CREATE INDEX IF NOT EXISTS idx_streetlights_geom
    ON streetlights USING gist (geom);

-- Unique: re-running the Mapillary ingestion must not duplicate detections.
CREATE UNIQUE INDEX IF NOT EXISTS ix_streetlights_mapillary_id
    ON streetlights (mapillary_id);

CREATE INDEX IF NOT EXISTS ix_streetlights_id
    ON streetlights (id);


-- ---------------------------------------------------------------------------
-- 3. Human ground-truth night audits
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS night_audits (
    id                   SERIAL NOT NULL,
    road_segment_id      INTEGER NOT NULL,
    rating               FLOAT NOT NULL,
    observed_light_count INTEGER,
    created_at           TIMESTAMP WITH TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY (road_segment_id) REFERENCES road_segments (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_night_audits_id
    ON night_audits (id);


-- ---------------------------------------------------------------------------
-- Verification
-- ---------------------------------------------------------------------------
--
-- After restoring, run these in the Supabase SQL editor. The first should
-- return three rows with non-zero counts; the second must list both GIST
-- indexes, or routing will be slow enough to stall a live demo.
--
--   SELECT 'road_segments' AS table, count(*) FROM road_segments
--   UNION ALL SELECT 'streetlights', count(*) FROM streetlights
--   UNION ALL SELECT 'night_audits', count(*) FROM night_audits;
--
--   SELECT indexname, indexdef
--   FROM pg_indexes
--   WHERE schemaname = 'public'
--     AND tablename IN ('road_segments', 'streetlights')
--     AND indexdef ILIKE '%gist%';
--
-- The data dump sets the id sequences itself (setval at the end of
-- chiraag_data.sql), so no manual sequence fix-up is needed.
