import copy
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts/map'))
import build_packed_release as builder
import plan_packed_releases as planner


class PackedReleasePackagingTests(unittest.TestCase):
    def test_inline_pinned_coverage_is_not_mutated_by_release_urls(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture=self.fixture(Path(temporary))
            fixture['manifest']['coverage']={'poly':{'file':'old.poly','url':'https://example/old.poly'}}
            fixture['entry']['extras']['poly']={'name':'old.poly','size':7}
            fixture['contents']['old.poly']=b'polygon'
            original=copy.deepcopy(fixture['entry'])
            self.build(fixture,fixture['workspace'])
            self.assertEqual(fixture['entry'],original)

    def test_stale_or_corrupt_gzip_is_atomically_regenerated_from_installed_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'roads.yspg';path.write_bytes(b'old geometry')
            builder.artifact(path,'tag','owner/repo',True)
            for content in [b'new geometry with different bytes',b'final geometry']:
                path.write_bytes(content)
                if content==b'final geometry':path.with_name(path.name+'.gz').write_bytes(b'truncated gzip')
                artifact=builder.artifact(path,'tag','owner/repo',True)
                self.assertEqual(gzip.decompress(path.with_name(path.name+'.gz').read_bytes()),content)
                self.assertEqual(artifact['uncompressed_sha256'],hashlib.sha256(content).hexdigest())
                self.assertEqual(artifact['uncompressed_bytes'],len(content))
            self.assertFalse(list(Path(temporary).glob('*.partial')))

    def test_raw_context_is_referenced_and_legacy_delta_and_parts_are_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture=self.fixture(Path(temporary))
            result=self.build(fixture,fixture['workspace'])
            root=fixture['workspace']/'fixture'/'bundle'
            manifest=json.loads((root/'fixture_manifest.json').read_text())
            self.assertIsNone(manifest['delta_index']);self.assertNotIn('db_parts',manifest)
            self.assertNotIn('compression',manifest['db'])
            self.assertTrue(manifest['db']['url'].endswith('.context.yspc'))
            names={item['file'] for item in result['release_files']}
            self.assertIn(manifest['db']['file'],names)
            self.assertFalse(any('delta_index' in name for name in names))
            for key in ['roads','nodes']:
                item=manifest['packed_base'][key];self.assertEqual(item['compression'],'gzip')
                self.assertIn(item['file']+'.gz',names)
                self.assertEqual(hashlib.sha256(gzip.decompress((root/(item['file']+'.gz')).read_bytes())).hexdigest(),item['uncompressed_sha256'])
            self.assertTrue(result['build_cache_identity'])

    def test_completed_cache_is_bound_to_plan_version_source_and_recipe(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture=self.fixture(Path(temporary));result=self.build(fixture,fixture['workspace'])
            with patch.object(builder,'download_asset',side_effect=AssertionError('Cached result must not download')):
                self.assertEqual(builder.build_one(fixture['plan'],fixture['entry'],fixture['workspace']),result)
            changed=copy.deepcopy(fixture['entry']);changed['bundle_version']='new-packed-generation'
            with self.assertRaisesRegex(ValueError,'recipe/source plan changed'):
                self.build(fixture,fixture['workspace'],changed)
            args=(fixture['plan'],fixture['entry'],fixture['manifest'],False)
            baseline=builder.cache_identity(*args,{'builder':'old'},'1.5.7')
            self.assertNotEqual(baseline,builder.cache_identity(*args,{'builder':'new'},'1.5.7'))
            self.assertNotEqual(baseline,builder.cache_identity(*args,{'builder':'old'},'new-encoder'))
            source=copy.deepcopy(fixture['manifest']);source['db']['sha256']='a'*64
            self.assertNotEqual(baseline,builder.cache_identity(fixture['plan'],fixture['entry'],source,False,{'builder':'old'},'1.5.7'))

    def test_explicit_staged_files_are_reused_only_with_full_source_bindings(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture=self.fixture(Path(temporary));self.build(fixture,fixture['workspace'])
            original=fixture['workspace']/'fixture';target=Path(temporary)/'adopted'/'fixture'
            shutil.copytree(original/'work',target/'work');shutil.copytree(original/'bundle',target/'bundle')
            with (patch.object(builder,'build_geometry',side_effect=AssertionError('Must reuse verified geometry')),
                  patch.object(builder,'build_context',side_effect=AssertionError('Must reuse verified context')),
                  patch.object(builder,'extract',side_effect=AssertionError('Must reuse verified source nodes'))):
                adopted=self.build(fixture,target.parent,keep_extract=True)
            self.assertTrue(adopted['verification']['every_original_geometry_text_exact'])
            geometry=target/'bundle'/('fixture_'+fixture['entry']['bundle_version']+'.ways.yspg')
            with self.assertRaisesRegex(ValueError,'another source SQLite'):
                builder.validate_container_binding(geometry,b'YSPGEO1\0','00'*32)
            old=geometry.read_bytes();codec1=bytearray(old);codec1[92:96]=(1).to_bytes(4,'little');geometry.write_bytes(codec1)
            with self.assertRaisesRegex(ValueError,'codec2'):
                builder.validate_container_binding(geometry,b'YSPGEO1\0',builder.digest(target/'work'/'source.sqlite'))
            geometry.write_bytes(old)
            context=target/'bundle'/('fixture_'+fixture['entry']['bundle_version']+'.context.yspc')
            database=sqlite3.connect(target/'work'/'source.sqlite')
            try:
                with self.assertRaisesRegex(ValueError,'packed_generation'):
                    builder.verify_logical_tables(database,context,geometry,'another-generation')
            finally:database.close()
            (target/'result.json').unlink()
            node_json=target/'work'/'sign-nodes.json';document=json.loads(node_json.read_text())
            document['source_sqlite_sha256']='00'*32;node_json.write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError,'node JSON source provenance'):
                self.build(fixture,target.parent)

    def test_planner_skips_published_v4_generations_without_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            def asset(identity,name,content):return {'id':identity,'name':name,'size':len(content),'digest':'sha256:'+hashlib.sha256(content).hexdigest()}
            db=b'database';manifest={'format':'youspeed.v3.bundle.manifest','region':'fixture','country_code':'DE',
                'bundle_version':'source','db':{'file':'db.gz','url':'https://github.com/owner/repo/releases/download/fixture/db.gz',
                'bytes':len(db),'sha256':hashlib.sha256(db).hexdigest()}}
            sources={1:json.dumps(manifest).encode(),4:json.dumps({'format':'youspeed.v4.bundle.manifest'}).encode()}
            def release(identity,tag,assets):return {'id':identity,'tag_name':tag,'draft':False,'html_url':'https://example/'+tag,'assets':assets}
            inventory=[release(1,'fixture',[asset(1,'fixture_manifest.json',sources[1]),asset(2,'db.gz',db)]),
                release(2,'fixture-pbf-latest',[asset(3,'fixture.osm.pbf',b'pbf')]),
                release(3,'fixture-packed-v1-2026-10-27',[asset(4,'fixture_manifest.json',sources[4])])]
            path=root/'inventory.json';path.write_text(json.dumps(inventory))
            def download(repo,item,output):
                output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(sources[item['id']]);return output
            with patch.object(planner,'download_asset',side_effect=download),patch.object(sys,'argv',
                ['planner','--inventory',str(path),'--workspace',str(root/'plan'),'--repo','owner/repo']):planner.main()
            plan=json.loads((root/'plan'/'plan.json').read_text())
            self.assertEqual(plan['failures'],[]);self.assertEqual(len(plan['bundles']),1)

    def fixture(self,root):
        source=root/'original.sqlite';db=sqlite3.connect(source)
        db.executescript('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE ways(way_id INTEGER PRIMARY KEY);CREATE TABLE way_geom(way_id INTEGER PRIMARY KEY,points_json TEXT);')
        db.execute("INSERT INTO metadata VALUES('country_code','DE')")
        db.execute('INSERT INTO ways VALUES(9007199254740993)')
        db.execute("INSERT INTO way_geom VALUES(9007199254740993,'[[49.0000000,8.0],[49.000001,8.000001]]')")
        db.commit();db.close()
        raw=source.read_bytes();compressed=gzip.compress(raw,mtime=0);pbf=b'fixture PBF bytes'
        manifest={'format':'youspeed.v3.bundle.manifest','schema_version':1,'variant':'v3','region':'fixture',
            'country_code':'DE','bundle_version':'source-1','min_app_version':'1.0',
            'db':{'file':'source.sqlite','bytes':len(compressed),'sha256':hashlib.sha256(compressed).hexdigest(),
                'compression':'gzip','uncompressed_bytes':len(raw),'uncompressed_sha256':hashlib.sha256(raw).hexdigest()},
            'db_parts':[{'file':'old-source.part1'}],'delta_index':{'file':'old-delta.json'}}
        entry={'region':'fixture','source_release_tag':'fixture','source_release_url':'https://example/fixture',
            'source_manifest_document':manifest,'release_tag':'fixture-packed-v1-2026-10-27','bundle_version':'2026-10-27-packed-v1',
            'manifest_file':'fixture_manifest.json','database_assets':[{'name':'source.sqlite.gz','size':len(compressed)}],
            'pbf_assets':[{'name':'source.osm.pbf','size':len(pbf)}],'extras':{}}
        return {'plan':{'repo':'owner/repo','version':'2026-10-27'},'entry':entry,'manifest':manifest,
            'workspace':root/'workspace','contents':{'source.sqlite.gz':compressed,'source.osm.pbf':pbf}}

    def build(self,fixture,workspace,entry=None,keep_extract=False):
        def download(repo,item,output):
            output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(fixture['contents'][item['name']]);return output
        def extract(pbf,source,output):
            output.write_text(json.dumps({'schema':'youspeed.generic-sign-nodes.v1','node_count':0,'nodes':[],
                'source_sqlite_sha256':builder.digest(source),'source_pbf_sha256':builder.digest(pbf)}))
        with patch.object(builder,'download_asset',side_effect=download):
            if keep_extract:return builder.build_one(fixture['plan'],entry or fixture['entry'],workspace,retain_work=True)
            with patch.object(builder,'extract',side_effect=extract):
                return builder.build_one(fixture['plan'],entry or fixture['entry'],workspace,retain_work=True)


if __name__=='__main__':unittest.main()
