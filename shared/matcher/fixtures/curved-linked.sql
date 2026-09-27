-- Mirrors iPhone SpeedConsumerTests.createLowSpeedSameRefJunctionFixtureDB.

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


        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (1, '12001', 'primary', 'Jahnstraße', 'B463', '50', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0000, 52.06000, 13.0041, 52.06000);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (12001, 13.0000, 13.0041, 52.06000, 52.06000);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (1, '12001', '[[52.06000,13.0000],[52.06000,13.0041]]');
        INSERT INTO way_endpoints(way_id, ref_norm, highway, tunnel_flag, start_node_key, start_lon, start_lat, end_node_key, end_lon, end_lat, way_length_m)
        VALUES (12001, 'B463', 'primary', 0, '130000000:520600000', 13.0000, 52.06000, '130041000:520600000', 13.0041, 52.06000, 280.3);

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (2, '12002', 'primary', 'Werderbrücke', 'B463', '50', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0041, 52.06000, 13.0100, 52.06000);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (12002, 13.0041, 13.0100, 52.06000, 52.06000);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (2, '12002', '[[52.06000,13.0041],[52.06000,13.0100]]');
        INSERT INTO way_endpoints(way_id, ref_norm, highway, tunnel_flag, start_node_key, start_lon, start_lat, end_node_key, end_lon, end_lat, way_length_m)
        VALUES (12002, 'B463', 'primary', 0, '130041000:520600000', 13.0041, 52.06000, '130100000:520600000', 13.0100, 52.06000, 404.5);

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (3, '12003', 'secondary', 'Calwer Straße', 'L1135', '30', NULL, NULL, NULL, NULL, 48.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0041, 52.06000, 13.0118, 52.0660);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (12003, 13.0041, 13.0118, 52.06000, 52.0660);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (3, '12003', '[[52.06000,13.0041],[52.06150,13.0041],[52.0660,13.0118]]');
        INSERT INTO way_endpoints(way_id, ref_norm, highway, tunnel_flag, start_node_key, start_lon, start_lat, end_node_key, end_lon, end_lat, way_length_m)
        VALUES (12003, 'L1135', 'secondary', 0, '130041000:520600000', 13.0041, 52.06000, '130118000:520660000', 13.0118, 52.0660, 711.0);

        INSERT INTO way_links(way_id, linked_way_id, shared_ref, link_kind, shared_node_key, shared_lon, shared_lat)
        VALUES
          (12001, 12002, 1, 'shared_endpoint', '130041000:520600000', 13.0041, 52.06000),
          (12002, 12001, 1, 'shared_endpoint', '130041000:520600000', 13.0041, 52.06000),
          (12001, 12003, 0, 'shared_endpoint', '130041000:520600000', 13.0041, 52.06000),
          (12003, 12001, 0, 'shared_endpoint', '130041000:520600000', 13.0041, 52.06000);
