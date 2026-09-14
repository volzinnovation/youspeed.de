"""Source-to-bundle regressions for opt-in settlement context bundles."""

import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/map"))

try:
    import shapely
    from shapely.geometry import Point, Polygon
    from settlement_context import Extractor, build_settlement_context
    from settlement_geometry import simplify_polygon
    from pack_runtime_artifacts_pyosmium import ArtifactHandler
    AVAILABLE = int(shapely.__version__.split(".")[0]) >= 2
except ImportError:
    AVAILABLE = False


class Fixture:
    def __init__(self):
        self.nodes = []
        self.ways = []
        self.relations = []
        self.roads = []

    def tags(self, tags):
        return "".join(f'<tag k="{escape(k)}" v="{escape(v)}"/>' for k, v in tags.items())

    def node(self, lon, lat, **tags):
        node_id = len(self.nodes) + 1
        self.nodes.append(f'<node id="{node_id}" lon="{lon}" lat="{lat}">{self.tags(tags)}</node>')
        return node_id

    def way(self, coords=None, refs=None, **tags):
        way_id = 100 + len(self.ways)
        if refs is None:
            refs = [self.node(lon, lat) for lon, lat in coords]
        self.ways.append(f'<way id="{way_id}">' + "".join(f'<nd ref="{n}"/>' for n in refs) + self.tags(tags) + '</way>')
        if "highway" in tags:
            self.roads.append((way_id, coords or [(8.0, 49.0), (8.01, 49.0)]))
        return way_id

    def multipolygon(self, outer, holes, **tags):
        members = []
        for role, ring in [("outer", outer)] + [("inner", ring) for ring in holes]:
            refs = [self.node(lon, lat) for lon, lat in ring[:-1]]
            refs.append(refs[0])
            way_id = self.way(refs=refs)
            members.append(f'<member type="way" ref="{way_id}" role="{role}"/>')
        relation_id = 1000 + len(self.relations)
        self.relations.append(f'<relation id="{relation_id}">' + "".join(members) + self.tags({"type": "multipolygon", **tags}) + '</relation>')
        return relation_id

    def write(self, path):
        path.write_text('<osm version="0.6">' + "".join(self.nodes + self.ways + self.relations) + '</osm>')


@unittest.skipUnless(AVAILABLE, "requires pyosmium and Shapely >= 2")
class SettlementContextTests(unittest.TestCase):
    def test_irrelevant_node_tags_are_not_iterated_or_location_accessed(self):
        class NonSignTags:
            def __init__(self):
                self.requested = []

            def get(self, key):
                self.requested.append(key)
                return {"name": "Unrelated place", "highway": "bus_stop"}.get(key)

            def __iter__(self):
                raise AssertionError("irrelevant node tags must not be iterated")

        class IrrelevantNode:
            tags = NonSignTags()

            @property
            def location(self):
                raise AssertionError("irrelevant node location must not be read")

        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        handler = Extractor(conn, 2)
        node = IrrelevantNode()
        handler.node(node)
        self.assertEqual(node.tags.requested, ["traffic_sign", "traffic_sign:forward", "traffic_sign:backward"])
        self.assertEqual(handler.signs, [])

    def build(self, fixture, country_code="DE"):
        ctx = tempfile.TemporaryDirectory()
        self.addCleanup(ctx.cleanup)
        path = Path(ctx.name) / "fixture.osm"
        fixture.write(path)
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.executescript("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE ways(way_id INTEGER PRIMARY KEY); CREATE TABLE way_geom(way_id INTEGER PRIMARY KEY,points_json TEXT);")
        for way_id, coords in fixture.roads:
            conn.execute("INSERT INTO ways VALUES(?)", (way_id,))
            conn.execute("INSERT INTO way_geom VALUES(?,?)", (way_id, json.dumps([[lat, lon] for lon, lat in coords])))
        build_settlement_context(conn, path, country_code=country_code)
        return conn, path

    def test_country_prefixed_context_is_supported_outside_germany(self):
        f = Fixture()
        urban = f.way([(8, 49), (8.01, 49)], highway="secondary", maxspeed="NL:urban")
        rural = f.way([(8, 49.1), (8.01, 49.1)], highway="secondary", **{"zone:traffic": "NL:rural"})
        conn, _ = self.build(f, country_code="NL")
        self.assertEqual(self.rows(conn, urban), [(0, 0, 1, "maxspeed_type", "high")])
        self.assertEqual(self.rows(conn, rural), [(0, 0, 0, "zone_traffic", "high")])

    def rows(self, conn, way_id):
        return conn.execute("SELECT segment_index,direction,inside_city,source,confidence FROM settlement_segment WHERE way_id=? ORDER BY segment_index,direction", (way_id,)).fetchall()

    def test_urban70_rural30_numeric_only_missing_and_explicit_conflict(self):
        f = Fixture()
        roads = [
            f.way([(8, 49), (8.01, 49)], highway="secondary", maxspeed="70", **{"zone:traffic": "DE:urban", "maxspeed:type": "sign"}),
            f.way([(8, 49.1), (8.01, 49.1)], highway="secondary", maxspeed="30", **{"source:maxspeed": "DE:rural"}),
            f.way([(8, 49.2), (8.01, 49.2)], highway="residential", maxspeed="30"),
            f.way([(8, 49.3), (8.01, 49.3)], highway="secondary", **{"zone:traffic": "DE:urban", "source:maxspeed": "DE:rural"}),
        ]
        conn, _ = self.build(f)
        self.assertEqual(self.rows(conn, roads[0]), [(0, 0, 1, "zone_traffic", "high")])
        self.assertEqual(self.rows(conn, roads[1]), [(0, 0, 0, "source_maxspeed", "high")])
        self.assertEqual(self.rows(conn, roads[2]), [(0, 0, None, "missing", "unknown")])
        self.assertEqual(self.rows(conn, roads[3]), [(0, 0, None, "conflict", "unknown")])
        self.assertEqual(conn.execute("SELECT value FROM metadata WHERE key='settlement_context_version'").fetchone(), ("1",))
        self.assertNotIn("state", [r[1] for r in conn.execute("PRAGMA table_info(settlement_segment)")])

    def test_symbolic_maxspeed_tags_are_typed_context_including_direction(self):
        f = Fixture()
        urban = f.way([(8, 49), (8.01, 49)], highway="secondary", maxspeed="DE:urban")
        rural = f.way([(8, 49.1), (8.01, 49.1)], highway="secondary", maxspeed="DE:rural")
        directed = f.way([(8, 49.2), (8.01, 49.2)], highway="secondary", **{"maxspeed:forward": "DE:urban", "maxspeed:backward": "DE:rural"})
        conn, _ = self.build(f)
        self.assertEqual(self.rows(conn, urban), [(0, 0, 1, "maxspeed_type", "high")])
        self.assertEqual(self.rows(conn, rural), [(0, 0, 0, "maxspeed_type", "high")])
        self.assertEqual(self.rows(conn, directed), [(0, -1, 0, "maxspeed_type", "high"), (0, 1, 1, "maxspeed_type", "high")])

    def test_zero_length_way_gets_explicit_null_context_and_report_count(self):
        f = Fixture()
        road = f.way([(8, 49), (8, 49)], highway="secondary", **{"zone:traffic": "DE:urban"})
        conn, _ = self.build(f)
        self.assertEqual(self.rows(conn, road), [(0, 0, None, "missing", "unknown")])
        self.assertEqual(conn.execute("SELECT value FROM metadata WHERE key='settlement_zero_length_way_count'").fetchone(), ("1",))

    def test_sign_splits_way_and_only_constrains_documented_direction(self):
        f = Fixture()
        a = f.node(8.0, 49)
        sign = f.node(8.005, 49, traffic_sign="DE:310", direction="forward")
        b = f.node(8.01, 49)
        road = f.way(refs=[a, sign, b], highway="secondary")
        conn, _ = self.build(f)
        self.assertEqual(self.rows(conn, road), [(0, -1, None, "missing", "unknown"), (0, 1, 0, "traffic_sign", "high"), (1, -1, None, "missing", "unknown"), (1, 1, 1, "traffic_sign", "high")])
        geometries = [json.loads(r[0]) for r in conn.execute("SELECT points_json FROM settlement_segment WHERE direction=1 ORDER BY segment_index")]
        self.assertEqual(geometries[0][-1], [49.0, 8.005])
        self.assertEqual(geometries[1][0], [49.0, 8.005])
        self.assertEqual(conn.execute("SELECT association,way_id FROM settlement_sign").fetchone(), ("node_membership", road))

    def test_paired_sign_faces_collapse_to_bidirectional_rows(self):
        f = Fixture()
        a = f.node(8.0, 49)
        sign = f.node(8.005, 49, **{"traffic_sign:forward": "DE:310", "traffic_sign:backward": "DE:311"})
        b = f.node(8.01, 49)
        road = f.way(refs=[a, sign, b], highway="secondary")
        conn, _ = self.build(f)
        self.assertEqual(self.rows(conn, road), [(0, 0, 0, "traffic_sign", "high"), (1, 0, 1, "traffic_sign", "high")])

    def test_generic_city_limit_default_and_both_are_double_sided(self):
        for extra in ({}, {"city_limit": "both"}):
            with self.subTest(extra=extra):
                f = Fixture()
                sign = f.node(8.005, 49, traffic_sign="city_limit", direction="forward", **extra)
                road = f.way(refs=[f.node(8, 49), sign, f.node(8.01, 49)], highway="secondary")
                conn, _ = self.build(f)
                self.assertEqual(self.rows(conn, road), [(0, 0, 0, "traffic_sign", "high"), (1, 0, 1, "traffic_sign", "high")])

    def test_generic_begin_and_end_remain_single_sided(self):
        for kind, before, after in (("begin", 0, 1), ("end", 1, 0)):
            with self.subTest(kind=kind):
                f = Fixture()
                sign = f.node(8.005, 49, traffic_sign="city_limit", city_limit=kind, direction="forward")
                road = f.way(refs=[f.node(8, 49), sign, f.node(8.01, 49)], highway="secondary")
                conn, _ = self.build(f)
                self.assertEqual(self.rows(conn, road), [(0, -1, None, "missing", "unknown"), (0, 1, before, "traffic_sign", "high"), (1, -1, None, "missing", "unknown"), (1, 1, after, "traffic_sign", "high")])

    def test_generic_city_limit_without_direction_stays_unknown(self):
        f = Fixture()
        sign = f.node(8.005, 49, traffic_sign="city_limit")
        road = f.way(refs=[f.node(8, 49), sign, f.node(8.01, 49)], highway="secondary")
        conn, _ = self.build(f)
        self.assertEqual(self.rows(conn, road), [(0, 0, None, "missing", "unknown")])
        self.assertEqual(conn.execute("SELECT inside_city,direction,association FROM settlement_sign").fetchone(), (None, 0, "direction_unknown"))

    def test_sign_on_collinear_way_split_constrains_both_ways(self):
        f = Fixture()
        sign = f.node(8.005, 49, traffic_sign="city_limit", direction="forward")
        incoming = f.way(refs=[f.node(8, 49), sign], highway="secondary")
        outgoing = f.way(refs=[sign, f.node(8.01, 49)], highway="secondary")
        conn, _ = self.build(f)
        self.assertEqual(self.rows(conn, incoming), [(0, 0, 0, "traffic_sign", "high")])
        self.assertEqual(self.rows(conn, outgoing), [(0, 0, 1, "traffic_sign", "high")])
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM settlement_sign WHERE association='collinear_way_split'").fetchone(), (4,))

    def test_undirected_sign_and_municipality_are_not_urban_proof(self):
        f = Fixture()
        a = f.node(8.0, 49)
        sign = f.node(8.005, 49, traffic_sign="DE:310")
        b = f.node(8.01, 49)
        road = f.way(refs=[a, sign, b], highway="secondary")
        f.multipolygon([(7.9, 48.9), (8.1, 48.9), (8.1, 49.1), (7.9, 49.1), (7.9, 48.9)], [], boundary="administrative", admin_level="8")
        conn, _ = self.build(f)
        self.assertEqual(self.rows(conn, road), [(0, 0, None, "missing", "unknown")])
        self.assertEqual(conn.execute("SELECT association FROM settlement_sign").fetchone(), ("direction_unknown",))

    def test_multipolygon_hole_splits_context_and_legacy_packer_retains_relation(self):
        for tags, source, confidence in [({"boundary": "urban"}, "urban_polygon", "high"), ({"landuse": "residential"}, "landuse", "low")]:
            with self.subTest(tags=tags):
                f = Fixture()
                road = f.way([(8.001, 49.005), (8.009, 49.005)], highway="secondary")
                relation = f.multipolygon([(8, 49), (8.01, 49), (8.01, 49.01), (8, 49.01), (8, 49)], [[(8.004, 49.004), (8.006, 49.004), (8.006, 49.006), (8.004, 49.006), (8.004, 49.004)]], **tags)
                conn, path = self.build(f)
                self.assertEqual(self.rows(conn, road), [(0, 0, 1, source, confidence), (1, 0, None, "missing", "unknown"), (2, 0, 1, source, confidence)])
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM settlement_ring WHERE is_hole=1").fetchone(), (1,))
                if source == "landuse":
                    handler = ArtifactHandler(24, 100, io.StringIO(), io.StringIO())
                    handler.apply_file(str(path), locations=True)
                    area = next(row for row in handler.areas if row["area_id"] == f"r:{relation}")
                    self.assertEqual(len(area["rings"]), 2)
                    self.assertIsNone(area["points"])

    def test_metric_simplification_preserves_deep_narrow_notch(self):
        ring = [(float(x), 0.) for x in range(11)] + [(10., 100.), (11., 100.)] + [(float(x), 0.) for x in range(11, 101)] + [(100., float(y)) for y in range(1, 151)] + [(float(x), 150.) for x in range(99, -1, -1)] + [(0., float(y)) for y in range(149, -1, -1)]
        def ll(p):
            return 8 + p[0] / 73000, 49 + p[1] / 111000
        polygon = Polygon([ll(p) for p in ring])
        point = Point(ll((10.5, 50)))
        simplified = simplify_polygon(polygon, 2)
        self.assertFalse(polygon.contains(point))
        self.assertFalse(simplified.contains(point))
        self.assertTrue(simplified.is_valid)

    def test_segment_ids_are_stable_when_unrelated_way_is_added(self):
        f = Fixture()
        way = f.way([(8, 49), (8.01, 49)], highway="secondary", **{"zone:traffic": "DE:urban"})
        conn, _ = self.build(f)
        first = conn.execute("SELECT segment_id FROM settlement_segment WHERE way_id=?", (way,)).fetchone()[0]
        f.way([(9, 49), (9.01, 49)], highway="secondary")
        conn2, _ = self.build(f)
        self.assertEqual(conn2.execute("SELECT segment_id FROM settlement_segment WHERE way_id=?", (way,)).fetchone()[0], first)

    def test_ambiguous_sign_is_retained_without_assigning_either_road(self):
        f = Fixture()
        sign = f.node(8.005, 49, traffic_sign="DE:310", direction="forward")
        f.way(refs=[f.node(8, 49), sign, f.node(8.01, 49)], highway="secondary")
        f.way(refs=[f.node(8.005, 48.99), sign, f.node(8.005, 49.01)], highway="secondary")
        conn, _ = self.build(f)
        self.assertEqual(conn.execute("SELECT association,way_id FROM settlement_sign").fetchone(), ("ambiguous_ways", None))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM settlement_segment WHERE inside_city IS NOT NULL").fetchone(), (0,))

    def test_conflicting_sign_and_road_context_is_unknown(self):
        f = Fixture()
        sign = f.node(8.005, 49, traffic_sign="DE:310", direction="forward")
        road = f.way(refs=[f.node(8, 49), sign, f.node(8.01, 49)], highway="secondary", **{"zone:traffic": "DE:rural"})
        conn, _ = self.build(f)
        row = conn.execute("SELECT inside_city,source FROM settlement_segment WHERE way_id=? AND segment_index=1 AND direction=1", (road,)).fetchone()
        self.assertEqual(row, (None, "conflict"))

    def test_cli_builder_opt_in_keeps_schema_and_all_legacy_tables(self):
        f = Fixture()
        f.way([(8, 49), (8.01, 49)], highway="secondary", **{"zone:traffic": "DE:urban"})
        ctx = tempfile.TemporaryDirectory()
        self.addCleanup(ctx.cleanup)
        folder = Path(ctx.name)
        source = folder / "fixture.osm"
        f.write(source)
        scripts = Path(__file__).resolve().parents[2] / "scripts/map"
        outputs = [str(folder / name) for name in ("ways.idx", "ways.meta", "areas.idx", "ways.lookup", "ways.geom", "ways.geom.lookup")]
        subprocess.run([sys.executable, str(scripts / "pack_runtime_artifacts_pyosmium.py"), str(source), *outputs], check=True, capture_output=True)
        db = folder / "pilot.sqlite"
        subprocess.run([sys.executable, str(scripts / "build_spatialite_v3.py"), "--v1-dist", str(folder), "--out-db", str(db), "--input-pbf", str(source), "--build-settlement-context", "--country-code", "DE"], check=True, capture_output=True)
        conn = sqlite3.connect(db)
        self.addCleanup(conn.close)
        self.assertEqual(conn.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone(), ("1",))
        self.assertEqual(conn.execute("SELECT inside_city FROM settlement_segment").fetchone(), (1,))
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"ways", "way_geom", "areas", "city_boundary", "city_ring", "city_place"} <= tables)


if __name__ == "__main__":
    unittest.main()
