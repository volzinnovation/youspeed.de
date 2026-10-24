-- Additive offline lookahead topology. Missing/unknown capability means STOP.
CREATE TABLE IF NOT EXISTS upcoming_path_capability(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS upcoming_path_way(
 way_id INTEGER PRIMARY KEY REFERENCES ways(way_id),
 restriction_barrier INTEGER NOT NULL CHECK(restriction_barrier IN(0,1)),
 geometry_verified INTEGER NOT NULL CHECK(geometry_verified IN(0,1))
);
CREATE TABLE IF NOT EXISTS upcoming_path_node(
 node_id INTEGER PRIMARY KEY,
 source_degree INTEGER NOT NULL CHECK(source_degree BETWEEN 0 AND 3),
 restriction_barrier INTEGER NOT NULL CHECK(restriction_barrier IN(0,1))
);
CREATE TABLE IF NOT EXISTS upcoming_path_segment(
 segment_id INTEGER PRIMARY KEY,
 way_id INTEGER NOT NULL REFERENCES ways(way_id),
 direction INTEGER NOT NULL CHECK(direction IN(-1,1)),
 start_chainage_m REAL NOT NULL,end_chainage_m REAL NOT NULL,
 start_node_id INTEGER NOT NULL,end_node_id INTEGER NOT NULL,
 length_m REAL NOT NULL,
 permission_status TEXT NOT NULL CHECK(permission_status IN('allowed','unknown','blocked')),
 CHECK(start_chainage_m>=0 AND end_chainage_m>start_chainage_m AND length_m>0),
 UNIQUE(way_id,direction,start_chainage_m,end_chainage_m)
);
CREATE INDEX IF NOT EXISTS idx_upcoming_path_segment_way ON upcoming_path_segment(way_id,direction,start_chainage_m);
CREATE INDEX IF NOT EXISTS idx_upcoming_path_segment_entry ON upcoming_path_segment(start_node_id);
CREATE TABLE IF NOT EXISTS upcoming_path_successor(
 from_segment_id INTEGER PRIMARY KEY REFERENCES upcoming_path_segment(segment_id),
 status TEXT NOT NULL CHECK(status IN('certified','stop')),
 to_segment_id INTEGER REFERENCES upcoming_path_segment(segment_id),
 via_node_id INTEGER NOT NULL,
 proof TEXT NOT NULL,
 CHECK((status='certified' AND to_segment_id IS NOT NULL AND proof='source_node_unbranched_unmerged_v1')
    OR (status='stop' AND to_segment_id IS NULL))
);
