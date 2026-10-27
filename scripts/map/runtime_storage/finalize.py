#!/usr/bin/env python3
"""Finalize integrity metadata, including exports from an already-running builder."""
import argparse
import json
from pathlib import Path
import sqlite3
import struct
import zlib

from build import ROAD, NODE, BLOCK


def finalize(output):
    path=output/'runtime.pack'
    with path.open('r+b') as f:
        header=f.read(160)
        values=struct.unpack_from('<8sII14Q',header)[3:]
        n,nodes,order,blocks,ro,go,gs,no,oo,bo,bd,total,blocksize,logical=values
        sections=[(ro,n*ROAD.size),(no,nodes*NODE.size),(oo,order*4),(bo,blocks*BLOCK.size)]
        checks=[]
        for off,size in sections:
            f.seek(off);crc=0
            while size:
                raw=f.read(min(size,1024*1024))
                if not raw:raise ValueError('Truncated output')
                crc=zlib.crc32(raw,crc);size-=len(raw)
            checks.append(crc)
        f.seek(132);f.write(struct.pack('<IIIII',*checks,0x43524331))
    d=sqlite3.connect(output/'runtime.sqlite')
    d.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',('way_count',str(n)));d.commit();d.close()
    manifest_path=output/'manifest.json'
    manifest=json.loads(manifest_path.read_text())
    manifest['section_crc32']=checks
    manifest['files']={p.name:{'bytes':p.stat().st_size} for p in output.iterdir() if p.is_file() and p.name!='manifest.json'}
    manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')
    return checks


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);a=p.parse_args()
    print(finalize(a.output))
