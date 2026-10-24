import json
import contextlib
import io
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/map'))
import traffic_sign_inventory as inventory
import generate_v3_country_bundles as bundles
import publish_v3_bundle as publisher


def feature(code='DE:310', group='00000000-0000-0000-0000-000000000001'):
    return {'type':'Feature','geometry':{'type':'Point','coordinates':[8.6,48.85]},'properties':{
        'GruppenID':group,'StandortID':'00000000-0000-0000-0000-000000000002',
        'GruppenReihung':0,'Verkehrszeichennummer':code,'GruppenAusrichtung':360,
        'Verwaltungsebene':'Neuenbürg','ARS':'082360044044','unknown_source_field':{'retained':True}}}


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'snapshot.json'
        self.db=sqlite3.connect(':memory:');self.db.executescript("CREATE TABLE ways(way_id INTEGER PRIMARY KEY,maxspeed TEXT);INSERT INTO ways VALUES(1,'30');CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);INSERT INTO metadata VALUES('schema_version','3');CREATE TABLE settlement_sign(sign_id TEXT);INSERT INTO settlement_sign VALUES('n:1:main');")
    def tearDown(self):
        self.db.close();self.tmp.cleanup()
    def write(self,rows):
        self.path.write_text(json.dumps({'type':'FeatureCollection','numberReturned':len(rows),'timeStamp':'2026-10-18T00:00:00Z','features':rows}))
    def test_all_codes_and_multi_sign_groups_preserve_raw_fields_without_changing_runtime(self):
        rows=[feature(),feature('DE:311'),feature('DE:274-50[WVZ Rombachtunnel]')];self.write(rows)
        report=inventory.import_inventory(self.db,self.path)
        self.assertEqual(report['record_count'],3)
        self.assertEqual(self.db.execute('SELECT * FROM ways').fetchall(),[(1,'30')])
        self.assertEqual(self.db.execute('SELECT * FROM metadata').fetchall(),[('schema_version','3')])
        self.assertEqual(self.db.execute('SELECT * FROM settlement_sign').fetchall(),[('n:1:main',)])
        raw=self.db.execute("SELECT raw_properties_json FROM traffic_sign_inventory WHERE sign_code='DE:311'").fetchone()[0]
        self.assertTrue(json.loads(raw)['unknown_source_field']['retained'])
        self.assertEqual(self.db.execute('SELECT usage_role FROM traffic_sign_source').fetchone()[0],'inventory_only')
        self.assertEqual(self.db.execute('SELECT count(*) FROM traffic_sign_inventory_rtree WHERE min_lon<=8.61 AND max_lon>=8.59 AND min_lat<=48.86 AND max_lat>=48.84').fetchone()[0],3)
    def test_repeat_import_is_idempotent_and_full_refresh_removes_stale_records(self):
        self.write([feature(),feature('DE:311')]);inventory.import_inventory(self.db,self.path)
        expected=self.db.execute('SELECT * FROM traffic_sign_inventory ORDER BY row_id').fetchall()
        inventory.import_inventory(self.db,self.path)
        self.assertEqual(expected,self.db.execute('SELECT * FROM traffic_sign_inventory ORDER BY row_id').fetchall())
        self.write([feature('DE:311')]);inventory.import_inventory(self.db,self.path)
        self.assertEqual(self.db.execute('SELECT sign_code FROM traffic_sign_inventory').fetchall(),[('DE:311',)])
        self.assertEqual(self.db.execute('SELECT count(*) FROM traffic_sign_inventory_rtree').fetchone()[0],1)
    def test_invalid_replacement_preserves_old_snapshot(self):
        self.write([feature()]);inventory.import_inventory(self.db,self.path)
        for rows in [[feature(),feature()],[],[feature()]]:
            if len(rows)==1:rows[0]['geometry']['coordinates'][0]=float('nan')
            self.write(rows)
            with self.assertRaises(ValueError):inventory.import_inventory(self.db,self.path)
            self.assertEqual(self.db.execute('SELECT sign_code FROM traffic_sign_inventory').fetchall(),[('DE:310',)])
    def test_sql_failure_rolls_back_schema_and_inventory_atomically(self):
        self.write([feature()])
        # A conflicting schema must not leave any newly created inventory tables behind.
        self.db.execute('CREATE TABLE traffic_sign_source(source_id TEXT PRIMARY KEY)')
        with self.assertRaises(sqlite3.OperationalError):inventory.import_inventory(self.db,self.path)
        self.assertIsNone(self.db.execute("SELECT name FROM sqlite_master WHERE name='traffic_sign_inventory'").fetchone())
    def test_only_bw_targets_are_automatically_enriched(self):
        for name in ['baden-wuerttemberg','germany/baden-wuerttemberg','germany-baden-wuerttemberg']:
            self.assertTrue(inventory.is_bw_region(name))
        for name in ['germany','karlsruhe-regbez','bayern','france']:
            self.assertFalse(inventory.is_bw_region(name))
    def test_bundle_orchestration_adds_inventory_only_for_bw_and_keeps_runtime_options(self):
        for region,iso2,iso3 in [('germany/baden-wuerttemberg','DE','DEU'),('bayern','DE','DEU'),('france','FR','FRA')]:
            target=bundles.BundleTarget('Country','country',iso2,iso3,region,'https://example.org/map.pbf',None,True)
            commands=bundles._bundle_commands(repo_root=ROOT,target=target,bundle_version='test',max_geom_points=64,
                db_compression='gzip',release_tag='unused',skip_release_urls=True,build_settlement_context=True)
            build=next(c for c in commands if any(x.endswith('build_spatialite_v3.py') for x in c))
            self.assertIn('--build-settlement-context',build)
            self.assertEqual('--traffic-sign-geojson' in build,region.endswith('baden-wuerttemberg'))
            self.assertEqual('--build-traffic-sign-runtime' in build,region.endswith('baden-wuerttemberg'))
            if region.endswith('baden-wuerttemberg'):
                self.assertIn('--build-way-links',build)
                self.assertEqual(build[build.index('--corridor-mode')+1],'paired')
            self.assertEqual(any('download' in c and any(x.endswith('traffic_sign_inventory.py') for x in c) for c in commands),region.endswith('baden-wuerttemberg'))
            if iso2=='FR': self.assertIn('--build-way-links',build)
    def test_local_bundle_manifest_includes_inventory_license_and_role(self):
        self.write([feature()]);inventory.import_inventory(self.db,self.path)
        source=Path(self.tmp.name)/'source.sqlite'
        self.db.commit()
        with sqlite3.connect(source) as disk:self.db.backup(disk)
        args=['publish_v3_bundle.py','--region','baden-wuerttemberg','--db',str(source),
              '--bundle-version','test','--out-root',str(Path(self.tmp.name)/'bundles')]
        with patch.object(sys,'argv',args),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(publisher.main(),0)
        manifest=json.loads((Path(self.tmp.name)/'bundles/baden-wuerttemberg/test/baden-wuerttemberg_manifest.json').read_text())
        provenance=manifest['source']['traffic_sign_inventory'][0]
        self.assertEqual(provenance['usage_role'],'inventory_only')
        self.assertEqual(provenance['license_id'],'dl-de/by-2-0')
        self.assertEqual(provenance['record_count'],1)
        self.assertEqual(manifest['schema_version'],1)

if __name__=='__main__':unittest.main()
