-- Synthetic legacy map for native delta security instrumentation. No user data.
PRAGMA page_size=4096;
PRAGMA journal_mode=DELETE;
CREATE TABLE ways(way_id INTEGER PRIMARY KEY,street_name TEXT,maxspeed TEXT);
CREATE VIRTUAL TABLE ways_rtree USING rtree(way_id,min_lon,max_lon,min_lat,max_lat);
CREATE TABLE way_geom(way_id INTEGER PRIMARY KEY,points_json TEXT);
CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
INSERT INTO ways VALUES(1,'Before','50');
INSERT INTO ways_rtree VALUES(1,8,8.1,48,48.1);
INSERT INTO way_geom VALUES(1,'[[48,8],[48.1,8.1]]');
INSERT INTO metadata VALUES('schema_version','3');
