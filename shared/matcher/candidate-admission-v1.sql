-- Deliberately insert distant low IDs before the closest ID, including a way ID
-- above IEEE-754's exact integer range. Geometry uses [latitude, longitude].
CREATE TABLE ways (
  way_id INTEGER PRIMARY KEY, highway TEXT, street_name TEXT, ref TEXT,
  maxspeed TEXT, maxspeed_type TEXT, source_maxspeed TEXT,
  approx_heading_deg REAL, service TEXT, tunnel TEXT,
  min_lon REAL NOT NULL, min_lat REAL NOT NULL, max_lon REAL NOT NULL, max_lat REAL NOT NULL
);
CREATE TABLE way_geom (way_id INTEGER PRIMARY KEY, points_json TEXT NOT NULL);
INSERT INTO ways VALUES
  (1, 'secondary', 'Far road', NULL, '90', NULL, NULL, 90, NULL, NULL, -0.001, 0.0005, 0.001, 0.0005),
  (2, 'secondary', 'Tied road two', NULL, '70', NULL, NULL, 90, NULL, NULL, -0.001, 0.0004, 0.001, 0.0004),
  (10, 'secondary', 'Tied road ten', NULL, '50', NULL, NULL, 90, NULL, NULL, -0.001, 0.0004, 0.001, 0.0004),
  (9007199254740993, 'secondary', 'Closest road', NULL, '30', NULL, NULL, 90, NULL, NULL, -0.001, 0, 0.001, 0);
INSERT INTO way_geom VALUES
  (1, '[[0.0005,-0.001],[0.0005,0.001]]'),
  (2, '[[0.0004,-0.001],[0.0004,0.001]]'),
  (10, '[[0.0004,-0.001],[0.0004,0.001]]'),
  (9007199254740993, '[[0,-0.001],[0,0.001]]');
