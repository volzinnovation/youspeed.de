#!/usr/bin/env python3
"""Convert one pinned published bundle into a complete immutable v4 generation."""
import argparse
import copy
from datetime import datetime, timezone
from contextlib import ExitStack
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import sqlite3
import struct
import tempfile
import time
import zlib

from extract_packed_sign_nodes import extract
from pack_sign_nodes import pack as pack_nodes
from packed_runtime import Reader, build_context, build_geometry, digest, require, zstd_library
from plan_packed_releases import download_asset


class Joined(io.RawIOBase):
    def __init__(self, paths):
        self.paths, self.stream = iter(paths), None

    def readable(self):
        return True

    def read(self, count=-1):
        require(count >= 0, 'Unbounded source read is disabled')
        result = bytearray()
        while len(result) < count:
            if self.stream is None:
                path = next(self.paths, None)
                if path is None:
                    break
                self.stream = Path(path).open('rb')
            value = self.stream.read(count-len(result))
            if not value:
                self.stream.close()
                self.stream = None
            else:
                result.extend(value)
        return bytes(result)

    def close(self):
        if self.stream is not None:
            self.stream.close()
        super().close()


def materialize(paths, artifact, output):
    if output.exists():
        expected = artifact.get('uncompressed_sha256', artifact['sha256'])
        require(digest(output) == expected, 'Existing materialized input hash mismatch')
        return output
    joined = Joined(paths)
    decoder = gzip.GzipFile(fileobj=joined) if artifact.get('compression') == 'gzip' else joined
    partial = output.with_name(output.name+'.partial')
    require(not partial.exists(), f'Interrupted materialization exists: {partial}')
    with partial.open('xb') as target:
        shutil.copyfileobj(decoder, target, 4*1024*1024)
    decoder.close()
    joined.close()
    expected = artifact.get('uncompressed_sha256', artifact['sha256'])
    require(digest(partial) == expected, 'Materialized input hash mismatch')
    if artifact.get('uncompressed_bytes') is not None:
        require(partial.stat().st_size == artifact['uncompressed_bytes'], 'Materialized input byte mismatch')
    partial.rename(output)
    return output


def artifact(path, tag, repo, compression=False):
    path = Path(path)
    installed_sha = digest(path)
    installed_bytes = path.stat().st_size
    download = path
    if compression:
        download = path.with_name(path.name+'.gz')
        valid = False
        if download.is_file():
            try:
                checksum, count = hashlib.sha256(), 0
                with gzip.open(download,'rb') as decoded:
                    for chunk in iter(lambda:decoded.read(1024*1024),b''):
                        count += len(chunk)
                        if count > installed_bytes:
                            break
                        checksum.update(chunk)
                valid = count == installed_bytes and checksum.hexdigest() == installed_sha
            except (OSError, EOFError, zlib.error):
                pass
        if not valid:
            with tempfile.NamedTemporaryFile(prefix=download.name+'.',suffix='.partial',dir=download.parent,delete=False) as target:
                temporary = Path(target.name)
                try:
                    with path.open('rb') as source, gzip.GzipFile(filename='',mode='wb',fileobj=target,compresslevel=6,mtime=0) as encoded:
                        shutil.copyfileobj(source,encoded,1024*1024)
                except BaseException:
                    temporary.unlink(missing_ok=True)
                    raise
            temporary.replace(download)
    result = {'file':path.name, 'bytes':download.stat().st_size, 'sha256':digest(download),
              'url':f'https://github.com/{repo}/releases/download/{tag}/{download.name}'}
    if compression:
        result.update(compression='gzip',uncompressed_bytes=installed_bytes,uncompressed_sha256=installed_sha)
    return result


def write_json(path, value):
    Path(path).write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')


def cache_identity(plan, entry, source_manifest, source_override, builder_files, encoder_version):
    recipe = {'version':1,'repo':plan['repo'],'plan_version':plan.get('version'),
              'entry':entry,'source_manifest':source_manifest,'local_full_bw_upgrade':source_override,
              'context_codec':2,'transport':{'context':'none','roads':'gzip','nodes':'gzip'},
              'zstd_encoder_version':encoder_version,'zlib_encoder_version':zlib.ZLIB_RUNTIME_VERSION,
              'builder_files_sha256':builder_files}
    encoded=json.dumps(recipe,sort_keys=True,separators=(',',':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def cached_result(final, output, expected_identity, entry):
    result=json.loads(final.read_text())
    require(result.get('build_cache_identity')==expected_identity,
            'Completed generation recipe/source plan changed; use a fresh workspace to rebuild: '+str(final.parent))
    for key in ['region','release_tag','bundle_version','source_release_tag']:
        require(result.get(key)==entry[key],'Completed generation identity changed: '+key)
    assets={item['file']:item for item in result['release_files']}
    require(len(assets)==len(result['release_files']),'Duplicate cached release assets')
    require(entry['manifest_file'] in assets,'Cached manifest is not verified')
    for name,item in assets.items():
        require(Path(name).name==name,'Unsafe cached release asset')
        require((output/name).is_file() and (output/name).stat().st_size==item['bytes'] and
                digest(output/name)==item['sha256'],'Completed release evidence missing')
    manifest=json.loads((output/entry['manifest_file']).read_text())
    require(manifest.get('format')=='youspeed.v4.bundle.manifest' and manifest.get('variant')=='v4' and
            manifest.get('bundle_version')==entry['bundle_version'] and manifest.get('region')==entry['region'] and
            manifest.get('delta_index') is None and not manifest.get('db_parts'), 'Cached manifest violates packed generation contract')
    require(manifest['db'].get('compression','none') in ('','none'), 'Cached context must use its native container compression')
    return result


def validate_container_binding(path, magic, source_sha):
    with Path(path).open('rb') as stream:header=stream.read(128)
    require(len(header)==128 and header[:8]==magic,'Cached container kind differs from expected artifact')
    require(struct.unpack_from('<I',header,92)[0]==2,'Cached production container must use codec2')
    require(header[96:128].hex()==source_sha,'Cached container belongs to another source SQLite image')
    reader=Reader(path)
    reader.close()


def validate_node_pack_binding(node_json, nodes):
    with tempfile.TemporaryDirectory(prefix='verify-node-pack-',dir=nodes.parent) as temporary:
        expected=Path(temporary)/'expected.yspn'
        pack_nodes(node_json,expected)
        require(nodes.stat().st_size==expected.stat().st_size and digest(nodes)==digest(expected),
                'Cached node pack differs from complete source node JSON')


def verify_logical_tables(original, context_path, geometry_path, generation=None):
    # The exact SQLite image is independently roundtripped by build_context.
    # Here also check every original logical row count and every geometry text.
    # Runtime VFS executes that same image; this build validator uses a scratch
    # materialization only, never a production app database.
    with ExitStack() as resources:
        context = Reader(context_path)
        resources.callback(context.close)
        geometry = Reader(geometry_path)
        resources.callback(geometry.close)
        import tempfile
        with tempfile.TemporaryDirectory(prefix='verify-',dir=context_path.parent) as temp:
            path = Path(temp)/'context.sqlite'
            with path.open('wb') as target:
                for offset in range(0,context.logical,1024*1024):
                    target.write(context.read(offset,1024*1024))
            database = sqlite3.connect(path)
            resources.callback(database.close)
            database.create_function('ysp_way_points_json',1,geometry.geometry)
            if generation is not None:
                for key,value in {'packed_geometry_version':'1','packed_geometry_file':geometry_path.name,
                                  'packed_geometry_sha256':digest(geometry_path),'packed_generation':generation}.items():
                    require(database.execute('SELECT value FROM metadata WHERE key=?',(key,)).fetchone()==(value,),
                            'Cached context capability/generation differs: '+key)
            tables=[]
            for name,sql in original.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
                if name.endswith(('_node','_parent','_rowid')) and original.execute('SELECT 1 FROM sqlite_master WHERE name=? AND sql LIKE ?', (name.rsplit('_',1)[0],'%USING rtree%')).fetchone():
                    continue
                if name=='metadata':
                    for key,value in original.execute('SELECT key,value FROM metadata'):
                        require(database.execute('SELECT value FROM metadata WHERE key=?',(key,)).fetchone()==(value,), 'Original metadata changed')
                    continue
                quoted='"'+name.replace('"','""')+'"'
                expected=original.execute('SELECT COUNT(*) FROM '+quoted).fetchone()[0]
                actual=database.execute('SELECT COUNT(*) FROM '+quoted).fetchone()[0]
                require(expected==actual,'Original logical table row count changed: '+name)
                tables.append({'name':name,'rows':expected})
            count=0
            for way,text in original.execute('SELECT way_id,points_json FROM way_geom'):
                require(geometry.geometry(way)==text,'Packed geometry differs from source JSON')
                count+=1
            require(database.execute('PRAGMA quick_check').fetchone()==('ok',),'Materialized context integrity failed')
            database.close()
        return {'all_original_logical_table_counts_preserved':True,'original_metadata_values_preserved':True,
                'every_original_geometry_text_exact':True,'geometry_rows':count,'tables':tables}


def build_one(plan, entry, workspace, *, prefer_local_bw=True, retain_work=False):
    started=time.monotonic();repo=plan['repo'];tag=entry['release_tag'];region=entry['region']
    target=Path(workspace)/entry['source_release_tag'];work=target/'work';output=target/'bundle'
    work.mkdir(parents=True,exist_ok=True);output.mkdir(exist_ok=True)
    final=target/'result.json'
    old_manifest=entry.get('source_manifest_document') or json.loads(Path(entry['source_manifest']).read_text())
    source_manifest=old_manifest
    builder_files={'scripts/map/'+name:digest(Path(__file__).parent/name) for name in
                   ['build_packed_release.py','packed_runtime.py','extract_packed_sign_nodes.py','pack_sign_nodes.py']}
    source_override=False
    local_root=Path('mapdata/bundles/v3/baden-wuerttemberg/2026-10-23-v1.5-journal-conditional')
    if prefer_local_bw and region=='baden-wuerttemberg' and (local_root/'baden-wuerttemberg_speeds.sqlite.gz').exists():
        source_manifest=json.loads((local_root/'baden-wuerttemberg_manifest.json').read_text())
        source_override=True
    identity=cache_identity(plan,entry,source_manifest,source_override,builder_files,
                            zstd_library().ZSTD_versionString().decode('ascii'))
    if final.exists():return cached_result(final,output,identity,entry)
    # Incomplete artifacts are not recipe-bound evidence. Refuse their reuse
    # across a changed plan/code recipe rather than combining old/new containers.
    marker=target/'build-recipe.json'
    if marker.exists():
        require(json.loads(marker.read_text()).get('identity')==identity,
                'Incomplete generation recipe changed; use a fresh workspace: '+str(target))
    else:
        # Explicitly staged containers can be adopted only after the source,
        # codec, metadata, full logical contents and node provenance checks below.
        write_json(marker,{'identity':identity})
    if (work/'source.sqlite').exists():
        # A staged exact image is verified by materialize below; do not fetch
        # its large compressed source again merely to resume verification.
        paths=[]
    elif source_override:
        paths=[local_root/'baden-wuerttemberg_speeds.sqlite.gz']
        require(digest(paths[0])==source_manifest['db']['sha256'],'Local full-BW source differs from manifest')
    else:
        paths=[download_asset(repo,a,work/a['name']) for a in entry['database_assets']]
    source=materialize(paths,source_manifest['db'],work/'source.sqlite')
    source_sha=digest(source)
    prefix=f'{region}_{entry["bundle_version"]}'
    geometry=output/(prefix+'.ways.yspg');context=output/(prefix+'.context.yspc');nodes=output/(prefix+'.nodes.yspn')
    original=sqlite3.connect('file:'+str(source.resolve())+'?mode=ro&immutable=1',uri=True)
    print('GEOMETRY',region,flush=True)
    if geometry.exists():validate_container_binding(geometry,b'YSPGEO1\0',source_sha)
    else:build_geometry(original,geometry,source_sha)
    print('CONTEXT',region,flush=True)
    verification=None
    if context.exists():
        validate_container_binding(context,b'YSPCTX1\0',source_sha)
        verification=verify_logical_tables(original,context,geometry,entry['bundle_version'])
    else:build_context(source,geometry,context,source_sha,entry['bundle_version'])
    print('SIGN NODES',region,flush=True)
    if source_override:
        pbf=Path('mapdata/raw/baden-wuerttemberg-260913.osm.pbf')
    else:
        pbf_paths=[download_asset(repo,a,work/a['name']) for a in entry['pbf_assets']]
        if len(pbf_paths)==1:
            pbf=pbf_paths[0]
        else:
            pbf=work/'source.osm.pbf'
            if not pbf.exists():
                with pbf.open('xb') as target_pbf:
                    for part in pbf_paths:
                        with part.open('rb') as stream:shutil.copyfileobj(stream,target_pbf,4*1024*1024)
    node_json=work/'sign-nodes.json'
    if not node_json.exists():extract(pbf,source,node_json)
    source_nodes=json.loads(node_json.read_text())
    require(source_nodes.get('schema')=='youspeed.generic-sign-nodes.v1' and
            source_nodes.get('source_sqlite_sha256')==source_sha and
            source_nodes.get('source_pbf_sha256')==digest(pbf), 'Cached node JSON source provenance mismatch')
    if nodes.exists():validate_node_pack_binding(node_json,nodes)
    else:pack_nodes(node_json,nodes)
    print('VERIFY',region,flush=True)
    if verification is None:verification=verify_logical_tables(original,context,geometry,entry['bundle_version'])
    original.close()
    source_nodes.pop('nodes')
    manifest=copy.deepcopy(source_manifest)
    manifest.update(format='youspeed.v4.bundle.manifest',schema_version=1,variant='v4',
        bundle_version=entry['bundle_version'],min_app_version='1.6',
        created_at_utc=datetime.now(timezone.utc).isoformat(),
        db=artifact(context,tag,repo,False),
        packed_base={'version':1,'roads':artifact(geometry,tag,repo,True),'nodes':artifact(nodes,tag,repo,True)})
    manifest.pop('db_parts',None)
    manifest['delta_index']=None
    for name,item in entry['extras'].items():
        downloaded=download_asset(repo,item,work/item['name'])
        destination=output/(prefix+'_'+item['name'])
        if not destination.exists():shutil.copyfile(downloaded,destination)
        if name=='poly':manifest.setdefault('coverage',{})['poly']=artifact(destination,tag,repo)
        else:manifest[name]=artifact(destination,tag,repo)
    manifest['self']={'file':entry['manifest_file'],'url':f'https://github.com/{repo}/releases/download/{tag}/{entry["manifest_file"]}'}
    manifest['source']=dict(source_manifest.get('source',{}))
    manifest['source']['packed_storage']={'version':1,'original_sqlite_sha256':source_sha,
        'original_bundle_version':source_manifest['bundle_version'],'previous_release':entry['source_release_url'],
        'local_full_bw_upgrade':source_override,'query_semantics':'Original SQL tables/indexes preserved; way_geom exact text supplied from immutable geometry pack.',
        'generic_sign_nodes':source_nodes,'context_codec':'zstd-15-independent-256KiB-frames',
        'builder_files_sha256':builder_files,
        'build_cache_identity':identity,
        'license':'ODbL-1.0','copyright':'OpenStreetMap contributors',
        'copyright_url':'https://www.openstreetmap.org/copyright'}
    write_json(output/entry['manifest_file'],manifest)
    write_json(output/(prefix+'_validation.json'),verification)
    installed=context.stat().st_size+geometry.stat().st_size+nodes.stat().st_size
    downloaded=sum(item['bytes'] for item in [manifest['db'],manifest['packed_base']['roads'],manifest['packed_base']['nodes']])
    result={'format':'youspeed.v4.release-comparison','schema_version':1,'region':region,'release_tag':tag,
        'bundle_version':entry['bundle_version'],'source_release_tag':entry['source_release_tag'],
        'source_bundle_version':source_manifest['bundle_version'],'local_source_upgrade':source_override,
        'source_sqlite_sha256':source_sha,'source_installed_bytes':source.stat().st_size,
        'builder_files_sha256':builder_files,
        'build_cache_identity':identity,
        'source_download_bytes':source_manifest['db']['bytes'],
        'previous_published_download_bytes':sum(a['size'] for a in entry['database_assets']),
        'packed_installed_bytes':installed,'packed_download_bytes':downloaded,
        'installed_change_percent':(installed/source.stat().st_size-1)*100,
        'download_change_percent':(downloaded/source_manifest['db']['bytes']-1)*100,
        'node_count':source_nodes['node_count'],'source_nodes':source_nodes,'verification':verification,
        'elapsed_seconds':time.monotonic()-started,'release_files':[]}
    # Raw installed files are local validation artifacts; upload only transports.
    from urllib.parse import unquote,urlparse
    referenced=[manifest['db'],manifest['packed_base']['roads'],manifest['packed_base']['nodes']]
    if manifest.get('coverage',{}).get('poly'):referenced.append(manifest['coverage']['poly'])
    if manifest.get('penalty_rules'):referenced.append(manifest['penalty_rules'])
    names={unquote(urlparse(item['url']).path.rsplit('/',1)[-1]) for item in referenced}
    names.update([entry['manifest_file'],prefix+'_validation.json'])
    for name in sorted(names):
        require(Path(name).name==name,'Unsafe release artifact name')
        path=output/name
        require(path.is_file(),'Missing referenced release artifact: '+name)
        result['release_files'].append({'file':name,'bytes':path.stat().st_size,'sha256':digest(path)})
    for item in referenced:
        name=unquote(urlparse(item['url']).path.rsplit('/',1)[-1])
        require((output/name).stat().st_size==item['bytes'] and digest(output/name)==item['sha256'],'Manifest dependency mismatch')
    write_json(final,result)
    if not retain_work:
        shutil.rmtree(work)
        # Installed companions can be reconstructed exactly from their verified
        # gzip transports; retain only one copy during the 55-region conversion.
        geometry.unlink();nodes.unlink()
    print('COMPLETE',region,json.dumps({k:result[k] for k in ['source_installed_bytes','source_download_bytes','packed_installed_bytes','packed_download_bytes','node_count']}),flush=True)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True);parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--target',default='all');parser.add_argument('--published-source-only',action='store_true')
    parser.add_argument('--retain-work',action='store_true')
    args=parser.parse_args();plan=json.loads(args.plan.read_text())
    entries=[x for x in plan['bundles'] if args.target=='all' or x['source_release_tag'] in args.target.split(',')]
    require(entries,'No requested bundles in pinned plan')
    entries.sort(key=lambda x:sum(a['size'] for a in x['database_assets']),reverse=True)
    for entry in entries:build_one(plan,entry,args.workspace,prefer_local_bw=not args.published_source_only,retain_work=args.retain_work)


if __name__=='__main__':main()
