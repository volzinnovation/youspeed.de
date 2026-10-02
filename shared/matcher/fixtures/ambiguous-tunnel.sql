-- Equivalent to SpeedConsumerTests.createAmbiguousTunnelPortalFixtureDB (iPhone), without way_links where optional.
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
        VALUES (1, '7101', 'primary', 'Surface Approach', 'B 10', '70', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0000, 52.01000, 13.0009, 52.01000);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (7101, 13.0000, 13.0009, 52.01000, 52.01000);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (1, '7101', '[[52.01000,13.0000],[52.01000,13.0009]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (2, '7102', 'primary', 'Tunnel Section', 'B 10', '70', NULL, NULL, NULL, NULL, 90.0, 'main', 'yes', NULL, NULL, 'underground', '-1', NULL, 13.0010, 52.01000, 13.0020, 52.01000);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (7102, 13.0010, 13.0020, 52.01000, 52.01000);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (2, '7102', '[[52.01000,13.0010],[52.01000,13.0020]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (3, '7103', 'primary', 'Surface Continuation', 'B 10', '70', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0010, 52.01008, 13.0020, 52.01008);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (7103, 13.0010, 13.0020, 52.01008, 52.01008);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (3, '7103', '[[52.01008,13.0010],[52.01008,13.0020]]');

        INSERT INTO corridor_progress(corridor_kind, corridor_id, side_node_key, way_id, start_depth_m, end_depth_m, start_depth_nodes, end_depth_nodes, corridor_span_m, corridor_span_nodes)
        VALUES
          ('tunnel', 1, 'tunnel-west', 7102, 0.0, 68.5, 1, 3, 68.5, 3),
          ('tunnel', 1, 'tunnel-east', 7102, 68.5, 0.0, 3, 1, 68.5, 3);

        INSERT INTO way_links(way_id, linked_way_id, shared_ref, link_kind, shared_node_key, shared_lon, shared_lat)
        VALUES
          (7101, 7102, 1, 'shared_endpoint', 'tunnel-west', 13.0010, 52.01000),
          (7102, 7101, 1, 'shared_endpoint', 'tunnel-west', 13.0010, 52.01000),
          (7101, 7103, 1, 'shared_endpoint', 'surface-branch', 13.0010, 52.01004),
          (7103, 7101, 1, 'shared_endpoint', 'surface-branch', 13.0010, 52.01004);
