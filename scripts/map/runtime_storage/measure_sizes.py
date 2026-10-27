#!/usr/bin/env python3
"""Count complete candidate bytes and deterministic gzip bytes without copies."""
import argparse
import hashlib
import json
from pathlib import Path
import zlib


def measure(path):
    h=hashlib.sha256();encoder=zlib.compressobj(6,zlib.DEFLATED,31);compressed=0
    with path.open('rb') as f:
        while raw:=f.read(1024*1024):
            h.update(raw);compressed+=len(encoder.compress(raw))
    compressed+=len(encoder.flush())
    return {'path':str(path.resolve()),'installed_bytes':path.stat().st_size,
            'gzip_level6_bytes':compressed,'sha256':h.hexdigest()}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--geodesk',type=Path);p.add_argument('--generic-nodes',type=Path)
    p.add_argument('--packed-nodes',type=Path);p.add_argument('--sqlite-nodes',type=Path);p.add_argument('--node-verification',type=Path)
    p.add_argument('--compact-globals',action='store_true',help='Use verified deduplicated runtime globals; retain the complete original archive only as external evidence')
    p.add_argument('--result',type=Path,required=True);a=p.parse_args()
    if a.compact_globals:
        proof=json.loads((a.output_dir/'compact-coverage-verification.json').read_text())
        index=json.loads((a.output_dir/'runtime-globals.index.json').read_text())
        assert proof['all_original_table_hashes_reconstructed_exactly'] and proof['source_tables']==index['source_table_count']
    prefix='runtime-globals' if a.compact_globals else 'source-semantics'
    paths={'packed':a.output_dir/'runtime.pack','sqlite':a.output_dir/'runtime.sqlite',
           'source_semantics':a.output_dir/(prefix+'.zblocks'),
           'source_semantics_index':a.output_dir/(prefix+'.index.json')}
    if not a.compact_globals:paths['manifest']=a.output_dir/'manifest.json'
    if a.geodesk:paths['geodesk']=a.geodesk
    if a.generic_nodes:paths['generic_nodes']=a.generic_nodes
    if a.packed_nodes or a.sqlite_nodes:
        assert a.packed_nodes and a.sqlite_nodes and a.node_verification
        proof=json.loads(a.node_verification.read_text())
        assert proof['full_source_records_byte_identical'] and proof['original_chainage_doubles_identical']
        paths['packed_nodes']=a.packed_nodes;paths['sqlite_nodes']=a.sqlite_nodes
    files={}
    for key,path in paths.items():
        files[key]=measure(path);print(key,files[key]['installed_bytes'],files[key]['gzip_level6_bytes'],flush=True)
    if a.compact_globals:
        runtime_manifest={'schema':1,'source_table_count':index['source_table_count'],
                          'every_original_table_hash_reconstructed':True,
                          'files':{key:{k:v[k] for k in ('path','installed_bytes','sha256')} for key,v in files.items()},
                          'external_source_only':['generic_nodes'] if a.packed_nodes and a.generic_nodes else [],
                          'semantics':'Every original source table resides exactly in native per-way records or runtime-global data, as mapped by the global index. Native node files preserve complete source JSON; the original node JSON and full duplicate source archive remain external evidence.'}
        manifest_path=a.output_dir/'runtime-manifest.json'
        manifest_path.write_text(json.dumps(runtime_manifest,indent=2)+'\n')
        files['manifest']=measure(manifest_path)
    common=['source_semantics','source_semantics_index','manifest']+(['generic_nodes'] if a.generic_nodes and not a.packed_nodes else [])
    groups={'packed':['packed']+(['packed_nodes'] if a.packed_nodes else [])+common,
            'optimized_sqlite':['sqlite']+(['sqlite_nodes'] if a.sqlite_nodes else [])+common}
    if a.geodesk:groups['geodesk_with_canonical_semantics']=['geodesk','sqlite']+(['sqlite_nodes'] if a.sqlite_nodes else [])+common
    totals={group:{field:sum(files[key][field] for key in keys) for field in ('installed_bytes','gzip_level6_bytes')} for group,keys in groups.items()}
    result={'files':files,'complete_candidate_components':groups,'complete_candidate_totals':totals,'all_original_table_coverage':'Verified deduplicated native per-way records plus runtime-global archive' if a.compact_globals else 'Full duplicate original-source audit archive retained in each candidate',
            'gzip':'Independent file gzip streams, level 6; computed without writing duplicate archives. Includes complete shared original semantic data in each candidate; native library/app binary excluded.'}
    a.result.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(totals,indent=2))
