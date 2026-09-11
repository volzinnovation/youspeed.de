-- Mirrors iPhone SpeedConsumerTests.createHeadingDisambiguationFixtureDB.

        CREATE TABLE ways (
          row_id INTEGER PRIMARY KEY,
          way_id TEXT NOT NULL UNIQUE,
          highway TEXT,
          street_name TEXT,
          ref TEXT,
          maxspeed TEXT,
          maxspeed_type TEXT,
          source_maxspeed TEXT,
          zone_maxspeed TEXT,
          traffic_sign TEXT,
          approx_heading_deg REAL,
          service TEXT,
          tunnel TEXT,
          bridge TEXT,
          covered TEXT,
          location TEXT,
          layer TEXT,
          level TEXT,
          min_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lon REAL NOT NULL,
          max_lat REAL NOT NULL
        );
        CREATE TABLE ways_rtree (way_id INTEGER, min_lon REAL, max_lon REAL, min_lat REAL, max_lat REAL);
        CREATE TABLE way_geom (
          row_id INTEGER PRIMARY KEY,
          way_id TEXT NOT NULL UNIQUE,
          points_json TEXT NOT NULL
        );
        CREATE TABLE way_links (
          way_id INTEGER NOT NULL,
          linked_way_id INTEGER NOT NULL,
          shared_ref INTEGER NOT NULL DEFAULT 0,
          link_kind TEXT NOT NULL,
          shared_node_key TEXT,
          shared_lon REAL,
          shared_lat REAL,
          PRIMARY KEY(way_id, linked_way_id)
        );
        CREATE TABLE corridor_progress (
          corridor_kind TEXT NOT NULL,
          corridor_id INTEGER NOT NULL,
          side_node_key TEXT NOT NULL,
          way_id INTEGER NOT NULL,
          start_depth_m REAL NOT NULL,
          end_depth_m REAL NOT NULL,
          start_depth_nodes INTEGER NOT NULL DEFAULT 0,
          end_depth_nodes INTEGER NOT NULL DEFAULT 0,
          corridor_span_m REAL NOT NULL,
          corridor_span_nodes INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY(corridor_kind, corridor_id, side_node_key, way_id)
        );

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (1, '1001', 'residential', 'East-West Way', NULL, '30', NULL, NULL, NULL, NULL, 90.0, 'parking_aisle', 'yes', NULL, NULL, 'underground', '-1', NULL, 13.0000, 51.9999, 13.0100, 52.0001);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (1001, 13.0000, 13.0100, 51.9999, 52.0001);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (1, '1001', '[[52.0000,13.0000],[52.0000,13.0100]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (2, '1002', 'residential', 'North-South Way', NULL, '50', NULL, NULL, NULL, NULL, 0.0, 'main', NULL, 'yes', NULL, NULL, '1', NULL, 13.0049, 51.9950, 13.0051, 52.0050);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (1002, 13.0049, 13.0051, 51.9950, 52.0050);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (2, '1002', '[[51.9950,13.0050],[52.0050,13.0050]]');
