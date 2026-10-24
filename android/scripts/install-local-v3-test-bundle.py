#!/usr/bin/env python3
"""Install a hash-verified local v3 bundle into an explicitly selected debug app.

The default accepts an emulator only. Physical installation requires the explicit
--allow-physical-device flag after user authorization. No HTTP publishing or data
clearing occurs; other-region downloads and the former active record are retained.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import uuid


def sha256(path):
    digest=hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True,type=Path)
    parser.add_argument('--serial',required=True,help='Explicit adb device serial')
    parser.add_argument('--allow-physical-device',action='store_true',help='Permit an explicitly user-authorized physical debug-app target')
    parser.add_argument('--package',default='de.youspeed.android.testhost')
    parser.add_argument('--adb',default=str(Path.home()/'Library/Android/sdk/platform-tools/adb'))
    args=parser.parse_args()
    if not re.fullmatch(r'emulator-\d+',args.serial) and not args.allow_physical_device:parser.error('Physical devices require explicit --allow-physical-device authorization')
    if not re.fullmatch(r'[A-Za-z0-9_.:-]+',args.serial):parser.error('Invalid adb device serial')
    if not re.fullmatch(r'de\.youspeed\.android\.(testhost|debug)',args.package):parser.error('Use the isolated/debug app, never the production application')
    manifest=json.loads(args.manifest.read_text())
    if manifest.get('format')!='youspeed.v3.bundle.manifest' or manifest.get('schema_version')!=1:parser.error('Expected the standard v3 bundle manifest')
    db=manifest['db']; logical_name=db['file']
    if Path(logical_name).name!=logical_name or logical_name in ('','.','..'):parser.error('Database filename must be a basename')
    compressed=db.get('compression')=='gzip'
    artifact_name=db.get('url') or (logical_name+'.gz' if compressed else logical_name)
    if not isinstance(artifact_name,str) or Path(artifact_name).name!=artifact_name:parser.error('Expected a local relative artifact URL, without network locations')
    artifact=args.manifest.parent/artifact_name
    if artifact.stat().st_size!=db['bytes'] or sha256(artifact)!=db['sha256']:parser.error('Download artifact hash or size mismatch')
    expected_sha=db['uncompressed_sha256'] if compressed else db['sha256']
    expected_bytes=db['uncompressed_bytes'] if compressed else db['bytes']
    adb=[args.adb,'-s',args.serial]
    def remote_command(command):
        # adb joins remote arguments before the device shell parses them. Preserve
        # sh -c as one quoted argument; shell -T also carries exit status/output.
        return [*adb,'shell','-T',shlex.join(['run-as',args.package,'sh','-c',command])]
    def remote(command,*,data=None,check=True):
        return subprocess.run(remote_command(command),input=data,check=check,capture_output=True)
    app_root=remote('pwd').stdout.decode().strip()
    if not app_root.startswith('/data/'):raise RuntimeError('Unexpected application directory')
    subprocess.run([*adb,'shell','am','force-stop',args.package],check=True)
    token=lambda value:re.sub(r'[^a-z0-9._-]+','-',value.strip().lower())
    relative=f'files/bundle/bundles/{token(manifest["region"])}/{token(manifest["bundle_version"])}'
    destination=f'{relative}/{logical_name}'
    if remote(f'test -e {shlex.quote(destination)}',check=False).returncode==0:parser.error('This bundle version is already installed; use a new version or remove it through the app')
    remote(f'mkdir -p {shlex.quote(relative)}')
    temporary=destination+'.installing'
    process=subprocess.Popen(remote_command(f'cat > {shlex.quote(temporary)}'),stdin=subprocess.PIPE)
    materialized_hash=hashlib.sha256(); materialized_bytes=0
    opener=gzip.open if compressed else open
    try:
        with opener(artifact,'rb') as source:
            while chunk:=source.read(1024*1024):
                materialized_hash.update(chunk);materialized_bytes+=len(chunk);process.stdin.write(chunk)
        process.stdin.close()
        if process.wait()!=0:raise RuntimeError('Device database transfer failed')
        if materialized_hash.hexdigest()!=expected_sha or materialized_bytes!=expected_bytes:raise RuntimeError('Materialized database hash or size mismatch')
        device_hash=remote(f'sha256sum {shlex.quote(temporary)}').stdout.decode().split()[0]
        if device_hash!=expected_sha:raise RuntimeError('Device database hash mismatch')
        poly=manifest.get('coverage',{}).get('poly')
        if poly:
            name=poly['file']
            if Path(name).name!=name:raise ValueError('Coverage polygon must be a basename')
            polygon=args.manifest.parent/name
            if polygon.stat().st_size!=poly['bytes'] or sha256(polygon)!=poly['sha256']:raise ValueError('Coverage polygon hash mismatch')
            remote(f'cat > {shlex.quote(relative+"/"+name)}',data=polygon.read_bytes())
        remote(f'mv {shlex.quote(temporary)} {shlex.quote(destination)}')
        remote(f'cat > {shlex.quote(relative+"/bundle-manifest.v3.json")}',data=args.manifest.read_bytes())
        active={'region':manifest['region'],'country_code':manifest.get('country_code'),'bundle_version':manifest['bundle_version'],
                'db_file_name':logical_name,'db_path':app_root+'/'+destination,'db_sha256':expected_sha,'db_bytes':expected_bytes,
                'manifest_url':'file://'+str(args.manifest.resolve()),'activated_at_utc':manifest['created_at_utc']}
        previous_backup='files/bundle/active_bundle.before-v15-test-'+uuid.uuid4().hex+'.json'
        remote('mkdir -p files/bundle; if test -f files/bundle/active_bundle.json; then cp files/bundle/active_bundle.json '+shlex.quote(previous_backup)+'; fi')
        remote('cat > files/bundle/active_bundle.json.installing',data=(json.dumps(active)+'\n').encode())
        remote('mv files/bundle/active_bundle.json.installing files/bundle/active_bundle.json')
    except BaseException:
        if process.poll() is None:process.kill();process.wait()
        remote(f'rm -f {shlex.quote(temporary)}',check=False)
        raise
    print(json.dumps({'package':args.package,'serial':args.serial,'db_path':active['db_path'],'sha256':expected_sha,'bytes':expected_bytes}))
    print('Restart the selected app with precise location available. The regional bundle is selected by existing coverage routing; no GPS fix is injected.')


if __name__=='__main__':main()
