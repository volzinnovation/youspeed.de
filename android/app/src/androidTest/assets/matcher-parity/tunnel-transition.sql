-- Equivalent to SpeedConsumerTests.createTunnelTransitionFixtureDB (iPhone), without way_links where optional.
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
          PRIMARY KEY(way_id, linked_way_id)
        );

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (1, '7001', 'primary', 'Surface Approach', 'B 10', '70', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0000, 51.99995, 13.0009, 52.00005);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (7001, 13.0000, 13.0009, 51.99995, 52.00005);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (1, '7001', '[[52.0000,13.0000],[52.0000,13.0009]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (2, '7002', 'primary', 'Tunnel Section', 'B 10', '70', NULL, NULL, NULL, NULL, 90.0, 'main', 'yes', NULL, NULL, 'underground', '-1', NULL, 13.0010, 51.99995, 13.0020, 52.00005);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (7002, 13.0010, 13.0020, 51.99995, 52.00005);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (2, '7002', '[[52.0000,13.0010],[52.0000,13.0020]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (3, '7003', 'primary', 'Surface Parallel', 'B 36', '50', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0010, 52.00020, 13.0020, 52.00030);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (7003, 13.0010, 13.0020, 52.00020, 52.00030);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (3, '7003', '[[52.00025,13.0010],[52.00025,13.0020]]');

        INSERT INTO way_links(way_id, linked_way_id, shared_ref, link_kind)
        VALUES
          (7001, 7002, 1, 'shared_endpoint'),
          (7002, 7001, 1, 'shared_endpoint');
