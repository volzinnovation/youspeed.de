-- Optional additive v3 capability. Old clients/regions need no migration.
CREATE TABLE IF NOT EXISTS traffic_sign_capability(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS traffic_sign_runtime(
 sign_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, record_key TEXT NOT NULL,
 snapshot_sha256 TEXT NOT NULL, sign_code TEXT NOT NULL, normalized_code TEXT NOT NULL,
 kind TEXT NOT NULL, numeric_value REAL, unit TEXT, parameter_status TEXT NOT NULL,
 lon REAL NOT NULL, lat REAL NOT NULL, orientation_deg REAL,
 display_radius_m REAL NOT NULL CHECK(display_radius_m IN (10,30)),
 pictogram_code TEXT, pictogram_path TEXT, model_classes_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_traffic_sign_runtime_position ON traffic_sign_runtime(lat,lon);
CREATE UNIQUE INDEX IF NOT EXISTS idx_traffic_sign_runtime_source ON traffic_sign_runtime(source_id,record_key);
CREATE TABLE IF NOT EXISTS traffic_sign_way_direction(
 way_id INTEGER PRIMARY KEY REFERENCES ways(way_id), oneway INTEGER NOT NULL CHECK(oneway IN (-1,0,1)),
 forward_allowed INTEGER NOT NULL, backward_allowed INTEGER NOT NULL,
 lanes INTEGER, lanes_forward INTEGER, lanes_backward INTEGER,
 maxspeed_forward TEXT, maxspeed_backward TEXT, lane_tags_json TEXT NOT NULL,
 start_node_key TEXT NOT NULL,end_node_key TEXT NOT NULL,way_length_m REAL NOT NULL,
 highway TEXT,ref TEXT,street_name TEXT
);
CREATE INDEX IF NOT EXISTS idx_sign_direction_start ON traffic_sign_way_direction(start_node_key);
CREATE INDEX IF NOT EXISTS idx_sign_direction_end ON traffic_sign_way_direction(end_node_key);
CREATE TABLE IF NOT EXISTS traffic_sign_lane(
 way_id INTEGER NOT NULL REFERENCES ways(way_id),direction INTEGER NOT NULL CHECK(direction IN (-1,1)),
 lane_index INTEGER NOT NULL,maxspeed TEXT,turns TEXT,access TEXT,
 source TEXT NOT NULL CHECK(source='osm'),PRIMARY KEY(way_id,direction,lane_index)
);
CREATE TABLE IF NOT EXISTS traffic_sign_association(
 sign_id TEXT PRIMARY KEY REFERENCES traffic_sign_runtime(sign_id),
 status TEXT NOT NULL,way_id INTEGER,direction INTEGER CHECK(direction IN (-1,1)),
 station_chainage_m REAL,local_heading_deg REAL,confidence REAL,
 evidence_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_traffic_sign_association_way ON traffic_sign_association(way_id,direction,status);
CREATE TABLE IF NOT EXISTS traffic_sign_way_rule(
 rule_id TEXT PRIMARY KEY,sign_id TEXT NOT NULL REFERENCES traffic_sign_runtime(sign_id),
 way_id INTEGER NOT NULL REFERENCES ways(way_id),direction INTEGER NOT NULL CHECK(direction IN (-1,1)),
 start_chainage_m REAL NOT NULL,end_chainage_m REAL NOT NULL,
 station_chainage_m REAL NOT NULL,local_heading_deg REAL NOT NULL,
 speed_kmh REAL,inside_city INTEGER CHECK(inside_city IN (0,1)),
 association_status TEXT NOT NULL,lane_scope TEXT NOT NULL,
 CHECK(start_chainage_m<=end_chainage_m)
);
CREATE INDEX IF NOT EXISTS idx_sign_way_rule_way ON traffic_sign_way_rule(way_id,direction,start_chainage_m);
CREATE TABLE IF NOT EXISTS traffic_sign_rule_path(
 rule_id TEXT PRIMARY KEY REFERENCES traffic_sign_way_rule(rule_id),
 origin_way_id INTEGER NOT NULL,way_directions_json TEXT NOT NULL
);
