-- Equivalent to SpeedConsumerTests.createMatchContinuityFixtureDB (iPhone), without way_links where optional.
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

        CREATE TABLE way_endpoints (
          way_id INTEGER PRIMARY KEY,
          ref_norm TEXT,
          highway TEXT,
          tunnel_flag INTEGER NOT NULL DEFAULT 0,
          start_node_key TEXT NOT NULL,
          start_lon REAL NOT NULL,
          start_lat REAL NOT NULL,
          end_node_key TEXT NOT NULL,
          end_lon REAL NOT NULL,
          end_lat REAL NOT NULL,
          way_length_m REAL NOT NULL
        );
        CREATE TABLE way_continuity_group (
          continuity_group_id INTEGER PRIMARY KEY,
          continuity_kind TEXT NOT NULL,
          source_relation_id INTEGER,
          ref_norm TEXT,
          street_name_norm TEXT,
          member_count INTEGER NOT NULL
        );
        CREATE TABLE way_continuity_membership (
          way_id INTEGER NOT NULL,
          continuity_group_id INTEGER NOT NULL,
          continuity_kind TEXT NOT NULL,
          PRIMARY KEY(way_id, continuity_group_id)
        );

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (1, '5001', 'primary', 'Bundesstrasse 10 West', 'B10', '70', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0000, 52.0001, 13.0040, 52.0001);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (5001, 13.0000, 13.0040, 52.0001, 52.0001);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (1, '5001', '[[52.0001,13.0000],[52.0001,13.0040]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (2, '5002', 'primary', 'Bundesstrasse 10 East', 'B10', '70', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0043, 52.0001, 13.0100, 52.0001);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (5002, 13.0043, 13.0100, 52.0001, 52.0001);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (2, '5002', '[[52.0001,13.0043],[52.0001,13.0100]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (3, '5003', 'residential', 'Nearby Side Road', NULL, '50', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0043, 52.00004, 13.0100, 52.00004);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (5003, 13.0043, 13.0100, 52.00004, 52.00004);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (3, '5003', '[[52.00004,13.0043],[52.00004,13.0100]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (4, '6001', 'secondary', 'History Road', NULL, '80', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0000, 52.0100, 13.0040, 52.0100);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (6001, 13.0000, 13.0040, 52.0100, 52.0100);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (4, '6001', '[[52.0100,13.0000],[52.0100,13.0040]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (5, '6002', 'secondary', 'History Road', NULL, '80', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0043, 52.01009, 13.0100, 52.01009);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (6002, 13.0043, 13.0100, 52.01009, 52.01009);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (5, '6002', '[[52.01009,13.0043],[52.01009,13.0100]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (6, '6003', 'tertiary', 'Competing Road', NULL, '60', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0043, 52.01006, 13.0100, 52.01006);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (6003, 13.0043, 13.0100, 52.01006, 52.01006);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (6, '6003', '[[52.01006,13.0043],[52.01006,13.0100]]');

        INSERT INTO way_endpoints(way_id, ref_norm, highway, tunnel_flag, start_node_key, start_lon, start_lat, end_node_key, end_lon, end_lat, way_length_m)
        VALUES
          (5001, 'B10', 'primary', 0, 'n5001s', 13.0000, 52.0001, 'n5001e', 13.0040, 52.0001, 274.0),
          (5002, 'B10', 'primary', 0, 'n5002s', 13.0043, 52.0001, 'n5002e', 13.0100, 52.0001, 391.0),
          (5003, '', 'residential', 0, 'n5003s', 13.0043, 52.00004, 'n5003e', 13.0100, 52.00004, 391.0),
          (6001, '', 'secondary', 0, 'n6001s', 13.0000, 52.0100, 'n6001e', 13.0040, 52.0100, 274.0),
          (6002, '', 'secondary', 0, 'n6002s', 13.0043, 52.01009, 'n6002e', 13.0100, 52.01009, 391.0),
          (6003, '', 'tertiary', 0, 'n6003s', 13.0043, 52.01006, 'n6003e', 13.0100, 52.01006, 391.0);

        INSERT INTO way_continuity_group(continuity_group_id, continuity_kind, source_relation_id, ref_norm, street_name_norm, member_count)
        VALUES
          (1, 'route_relation_connected', 9001, 'B10', 'bundesstrasse 10', 2),
          (2, 'same_street_name_connected', NULL, '', 'history road', 2);

        INSERT INTO way_continuity_membership(way_id, continuity_group_id, continuity_kind)
        VALUES
          (5001, 1, 'route_relation_connected'),
          (5002, 1, 'route_relation_connected'),
          (6001, 2, 'same_street_name_connected'),
          (6002, 2, 'same_street_name_connected');
