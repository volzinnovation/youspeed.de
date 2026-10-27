#!/usr/bin/env python3
"""Stream the existing source-complete YSPNODE1 format, including empty regions."""
import argparse
import json
from pathlib import Path
import shutil
import struct
import tempfile
import zlib

RECORD=struct.Struct('<qiiQIIIQ')


def fnv(data):
    value=14695981039346656037
    for byte in data:value=((value^byte)*1099511628211)&((1<<64)-1)
    return value


def pack(source,output):
    output=Path(output)
    if output.exists():raise ValueError(f'Refusing to overwrite {output}')
    document=json.loads(Path(source).read_text())
    rows=document['nodes']
    if len(rows)!=document['node_count']:raise ValueError('Node count mismatch')
    if len({row['osm_node_id'] for row in rows})!=len(rows):raise ValueError('Duplicate node IDs')
    rows.sort(key=lambda row:(round(row['latitude']*1e7),round(row['longitude']*1e7),row['osm_node_id']))
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='nodes-',dir=output.parent) as temp:
        blob=Path(temp)/'blob';records=bytearray();encoded_offset=0
        with blob.open('wb') as stream:
            for row in rows:
                raw=json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
                if not 0<len(raw)<=1024*1024:raise ValueError('Oversized canonical sign node')
                latitude,longitude=round(row['latitude']*1e7),round(row['longitude']*1e7)
                if latitude/1e7!=row['latitude'] or longitude/1e7!=row['longitude']:raise ValueError('Non-E7 source node')
                encoded=zlib.compress(raw,9)
                records.extend(RECORD.pack(row['osm_node_id'],latitude,longitude,encoded_offset,len(encoded),len(raw),zlib.crc32(raw),fnv(raw)))
                stream.write(encoded);encoded_offset+=len(encoded)
        order=b''.join(struct.pack('<I',index) for index in sorted(range(len(rows)),key=lambda i:rows[i]['osm_node_id']))
        record_offset=128;order_offset=record_offset+len(records);blob_offset=order_offset+len(order)
        header=bytearray(128)
        struct.pack_into('<8sIIQQQQQII',header,0,b'YSPNODE1',1,0x01020304,len(rows),record_offset,order_offset,blob_offset,blob_offset+encoded_offset,zlib.crc32(records),zlib.crc32(order))
        struct.pack_into('<I',header,64,zlib.crc32(header[:64]))
        with output.open('xb') as target:
            target.write(header);target.write(records);target.write(order)
            with blob.open('rb') as stream:shutil.copyfileobj(stream,target,1024*1024)
    return {key:value for key,value in document.items() if key!='nodes'}|{'file':output.name,'bytes':output.stat().st_size}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('source',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();print(json.dumps(pack(args.source,args.output),indent=2))
