#!/usr/bin/env python3
"""Deduplicate the complete source archive against exact native per-way records.

No hot-file changes. Every original table's exact canonical hash must reconstruct
before the new shared runtime-global archive is accepted. The larger original
archive remains external audit evidence.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import zlib

from build import BLOCK_SIZE, ROAD, RELATED, Blocks, canonical
from verify import Pack


def sortable(value):
    if value is None:return (0,0)
    if isinstance(value,(int,float)):return (1,value)
    return (2,value)


def compact(source,output,verification):
    started=time.perf_counter()
    original=json.loads((output/'source-semantics.index.json').read_text())
    fullproof=json.loads(verification.read_text())
    assert fullproof['complete_original_source_archive_verified']
    assert fullproof['all_source_per_way_rows_exact_in_both_backends']
    db=sqlite3.connect('file:'+str(source.resolve())+'?mode=ro&immutable=1',uri=True)
    eligible={}
    for table in ('ways',*RELATED):
        if table not in original['tables']:continue
        info=original['tables'][table]
        assert info['order_by']!=['rowid'],('need explicit reconstruction order',table)
        if table!='ways':
            missing=db.execute(f'SELECT count(*) FROM "{table}" t LEFT JOIN ways w ON t.way_id=w.way_id WHERE w.way_id IS NULL').fetchone()[0]
            if missing:
                print('retain globals for orphan rows',table,missing,flush=True)
                continue
        eligible[table]=info
    db.close()
    preflight={'eligible_embedded_tables':list(eligible),'source_connection_closed':True}
    (output/'compact-preflight.json').write_text(json.dumps(preflight,indent=2)+'\n')
    print('preflight source SQL complete; source connection closed',flush=True)
    pack=Pack(output/'runtime.pack')
    hashes={t:hashlib.sha256() for t in eligible}
    counts={t:0 for t in eligible}
    last={}
    keys={t:[i['columns'].index(c) for c in i['order_by']] for t,i in eligible.items()}
    # Only sign/rule hash-ID tables need a bounded global sort; graph segment
    # IDs encode way identity and therefore remain ordered across source ways.
    buffered={t:[] for t,i in eligible.items() if i['order_by'][0]!='way_id' and t not in ('settlement_segment','upcoming_path_segment')}
    for idx in range(pack.count):
        road=ROAD.unpack_from(pack.map,pack.road_offset+idx*ROAD.size)
        data=json.loads(pack.metadata(road))
        for table,info in eligible.items():
            rows=[data['ways']] if table=='ways' else data.get(table,[])
            def key(row):return tuple(sortable(row[i]) for i in keys[table])
            rows.sort(key=key)
            for row in rows:
                rowkey=key(row)
                encoded=canonical(row)+b'\n'
                if table in buffered:
                    buffered[table].append((rowkey,encoded))
                else:
                    assert table not in last or last[table]<rowkey,('non-monotone embedded primary key; cannot compact safely',table,rowkey)
                    hashes[table].update(encoded)
                    last[table]=rowkey
                counts[table]+=1
        if (idx+1)%100000==0:
            print('reconstructed ways',idx+1,'seconds',round(time.perf_counter()-started,1),flush=True)
    for table,rows in buffered.items():
        rows.sort(key=lambda v:v[0])
        for rowkey,encoded in rows:
            assert table not in last or last[table]<rowkey,('duplicate embedded primary key',table,rowkey)
            hashes[table].update(encoded);last[table]=rowkey
    proofs={}
    for table,info in eligible.items():
        actual=hashes[table].hexdigest()
        assert actual==info['sha256'],('reconstructed original table hash mismatch',table,actual,info['sha256'])
        assert counts[table]==info['rows'],('reconstructed original table count mismatch',table)
        proofs[table]={'rows':counts[table],'original_sha256':info['sha256'],'reconstructed_sha256':actual}
        print('exact reconstruction',table,counts[table],flush=True)
    globals_path=output/'runtime-globals.zblocks'
    if globals_path.exists():raise FileExistsError(globals_path)
    writer=Blocks(globals_path)
    tables=copy.deepcopy(original['tables'])
    f=(output/'source-semantics.zblocks').open('rb')
    cached={}
    def source_bytes(offset,left):
        while left:
            i,pos=divmod(offset,BLOCK_SIZE)
            if i not in cached:
                off,size,rawsize,crc=original['blocks'][i]
                f.seek(off);raw=zlib.decompress(f.read(size))
                assert len(raw)==rawsize and zlib.crc32(raw)==crc
                cached.clear();cached[i]=raw
            raw=cached[i];n=min(left,len(raw)-pos)
            assert n>0
            yield raw[pos:pos+n];left-=n;offset+=n
    for table,info in tables.items():
        if table in eligible:
            info['storage']='native_per_way_semantic_records'
            info.pop('logical_offset');info.pop('logical_bytes')
        else:
            h=hashlib.sha256();start=writer.logical
            for raw in source_bytes(info['logical_offset'],info['logical_bytes']):
                h.update(raw);writer.append(raw)
            assert h.hexdigest()==info['sha256'],('global original table hash mismatch',table)
            info['storage']='runtime_globals'
            info['logical_offset']=start
            assert writer.logical-start==info['logical_bytes']
            proofs[table]={'rows':info['rows'],'original_sha256':info['sha256'],'reconstructed_sha256':h.hexdigest()}
            print('global original table exact',table,info['rows'],flush=True)
    writer.finish();f.close();pack.close()
    index={'format':'youspeed-runtime-globals-1','block_size':BLOCK_SIZE,'blocks':writer.entries,'tables':tables,
           'embedded_files':['runtime.pack OR runtime.sqlite'],'source_table_count':len(tables),
           'source_geometry_json_lexical_bytes_preserved':True,
           'description':'Every original typed row/column reconstructs to its exact original canonical table hash. Per-way rows reside once in the chosen backend; remaining rows including raw geometry JSON live in these global blocks. Full source-semantics archive is external audit evidence, not required runtime payload.'}
    (output/'runtime-globals.index.json').write_bytes(canonical(index))
    report={'all_original_table_hashes_reconstructed_exactly':True,'source_tables':len(proofs),
            'table_proofs':proofs,'per_way_embedded_tables':list(eligible),
            'global_archive_bytes':globals_path.stat().st_size,'global_index_bytes':(output/'runtime-globals.index.json').stat().st_size,
            'external_audit_archive_bytes':(output/'source-semantics.zblocks').stat().st_size,
            'raw_geometry_json_spelling_preserved':True,'elapsed_seconds':time.perf_counter()-started}
    (output/'compact-coverage-verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='table_proofs'},indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--full-verification',type=Path,required=True)
    a=p.parse_args();compact(a.source,a.output_dir,a.full_verification)
