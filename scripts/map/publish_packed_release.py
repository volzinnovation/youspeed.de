#!/usr/bin/env python3
"""Stage verified v4 assets as drafts; publication additionally requires device QA."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import quote,unquote,urlparse
from packed_runtime import digest,require


def run(args,**options):return subprocess.run(['gh',*args],check=True,**options)


def validate_qa(qa,result,manifest,source_commit):
    require(qa.get('format')=='youspeed.packed-runtime.rollout-qa' and qa.get('schema_version')==1,'Unknown QA report')
    require(qa.get('ready_for_rollout') is True and set(qa.get('physical_devices_passed',[]))=={'iphone','android'},'Both physical phones must pass')
    require(qa.get('source_commit')==source_commit,'QA belongs to another source commit')
    require(qa.get('mapped_payload_bytes')==0 and qa.get('observed_incremental_rss_gate_bytes')==64*1024*1024,'Low-RSS gate missing')
    require(qa.get('builder_files_sha256')==result['builder_files_sha256'],'Untested builder recipe')
    require(manifest['source']['packed_storage']['context_codec']=='zstd-15-independent-256KiB-frames','Untested context codec')
    required={'shared/runtime-storage-prototype/packed_runtime.cpp',
              'shared/runtime-storage-prototype/packed_runtime.h',
              'shared/runtime-storage-prototype/packed_sqlite_vfs.cpp',
              'shared/runtime-sign-nodes-prototype/runtime_sign_nodes.cpp',
              'android/app/src/main/cpp/packed_sqlite_jni.cpp',
              'android/app/src/main/java/de/youspeed/android/alpha/RuntimeSqlDatabase.kt',
              'iphone/SpeedConsumerApp/PackedBundleRuntime.swift'}
    sources=qa.get('runtime_source_sha256',{})
    require(required<=set(sources),'QA omits production runtime sources')
    for path,expected in {**sources,**qa['builder_files_sha256']}.items():
        require(not Path(path).is_absolute() and '..' not in Path(path).parts,'Unsafe QA source path')
        raw=subprocess.check_output(['git','show',source_commit+':'+path])
        require(hashlib.sha256(raw).hexdigest()==expected,'QA source hash differs: '+path)
    tested=qa.get('tested_bw_artifacts',{})
    require(set(tested)=={'context','roads','nodes'},'QA omits tested BW generation')
    if result['region']=='baden-wuerttemberg':
        actual=dict(zip(['context','roads','nodes'],[manifest['db'],manifest['packed_base']['roads'],manifest['packed_base']['nodes']]))
        for name,item in actual.items():
            require(tested[name]=={'bytes':item.get('uncompressed_bytes',item['bytes']),
                                  'sha256':item.get('uncompressed_sha256',item['sha256'])},'BW release differs from tested phone data')
    for platform in ['iphone','android']:
        evidence=qa.get('physical_device_evidence',{}).get(platform,{})
        require(evidence.get('lookup_results_identical') is True and
                0<=evidence.get('observed_incremental_rss_bytes',2**63)<64*1024*1024 and
                evidence.get('retained_reader_count',0)>=8 and
                evidence.get('pool_lookup_results_identical') is True and
                0<=evidence.get('pool_observed_incremental_rss_bytes',2**63)<56*1024*1024 and
                evidence.get('mapped_payload_bytes')==0 and
                re.fullmatch('[0-9a-f]{64}',evidence.get('report_sha256','')) and
                re.fullmatch('[0-9a-f]{64}',evidence.get('pool_report_sha256','')),'Invalid physical-device evidence: '+platform)


def tag_commit(repo,tag):
    response=subprocess.run(['gh','api',f'repos/{repo}/commits/{quote(tag,safe="")}'],capture_output=True,text=True)
    if response.returncode:
        # GitHub creates a missing tag when a draft is published, not staged.
        require('HTTP 404' in response.stderr,'Could not verify existing tag commit')
        return None
    return json.loads(response.stdout)['sha']


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--result',type=Path,required=True)
    p.add_argument('--repo',default='volzinnovation/youspeed.de');p.add_argument('--source-commit',required=True)
    p.add_argument('--publish',action='store_true');p.add_argument('--qa-report',type=Path)
    p.add_argument('--publish-staged',action='store_true',help='Verify existing draft assets on GitHub and publish without downloading/reuploading payloads')
    a=p.parse_args();require(re.fullmatch(r'[0-9a-f]{40}',a.source_commit),'Source commit must be pinned')
    require(not a.publish_staged or a.publish,'--publish-staged also requires --publish and bound device QA')
    result=json.loads(a.result.read_text());root=a.result.parent/'bundle';tag=result['release_tag']
    require(re.fullmatch(r'[a-z0-9][a-z0-9._-]*',tag),'Unsafe release tag')
    manifest_name=result['region']+'_manifest.json'
    if a.publish_staged:
        staged=json.loads(subprocess.check_output(['gh','api',f'repos/{a.repo}/releases/tags/{tag}'],text=True))
        require(staged['draft'] and staged['target_commitish']==a.source_commit,'Staged release does not match tested builder commit')
        remote_manifest=next((x for x in staged['assets'] if x['name']==manifest_name),None)
        require(remote_manifest is not None,'Staged manifest missing')
        raw=subprocess.check_output(['gh','api',f'repos/{a.repo}/releases/assets/{remote_manifest["id"]}','-H','Accept: application/octet-stream'])
        expected=next(x for x in result['release_files'] if x['file']==manifest_name)
        require(len(raw)==expected['bytes'] and hashlib.sha256(raw).hexdigest()==expected['sha256'],'Staged manifest differs from build receipt')
        manifest=json.loads(raw)
    else:manifest=json.loads((root/manifest_name).read_text())
    require(manifest['format']=='youspeed.v4.bundle.manifest' and manifest['min_app_version']=='1.6','Invalid packed release')
    require(manifest.get('delta_index') is None and not manifest.get('db_parts'),'Packed releases cannot use SQL deltas/source parts')
    require(manifest['bundle_version']==result['bundle_version'] and manifest['region']==result['region'],'Release identity differs')
    provenance=manifest['source']['packed_storage']
    require(provenance['builder_files_sha256']==result['builder_files_sha256'] and
            provenance['original_sqlite_sha256']==result['source_sqlite_sha256'],'Release provenance differs')
    require(all(result['verification'].get(key) is True for key in
            ['all_original_logical_table_counts_preserved','original_metadata_values_preserved','every_original_geometry_text_exact']),
            'Original-source verification incomplete')
    assets={item['file']:item for item in result['release_files']}
    require(len(assets)==len(result['release_files']) and manifest_name in assets,'Duplicate/missing release assets')
    for name,item in assets.items():
        require(Path(name).name==name,'Unsafe release asset')
        if not a.publish_staged:
            require((root/name).stat().st_size==item['bytes'] and digest(root/name)==item['sha256'],'Unverified release asset: '+name)
    prefix=f'https://github.com/{a.repo}/releases/download/{tag}/'
    require(manifest['self']=={'file':manifest_name,'url':prefix+manifest_name},'Manifest self URL differs')
    dependencies=[manifest['db'],manifest['packed_base']['roads'],manifest['packed_base']['nodes']]
    if manifest.get('coverage',{}).get('poly'):dependencies.append(manifest['coverage']['poly'])
    if manifest.get('penalty_rules'):dependencies.append(manifest['penalty_rules'])
    for item in dependencies:
        name=unquote(urlparse(item['url']).path.rsplit('/',1)[-1]);require(name in assets,'Missing runtime release dependency')
        require(item['url']==prefix+name,'Artifact URL points outside this release')
        require(assets[name]['bytes']==item['bytes'] and assets[name]['sha256']==item['sha256'],'Runtime manifest/asset mismatch')
    if a.publish:
        require(a.qa_report is not None,'Publication requires completed physical-device QA')
        validate_qa(json.loads(a.qa_report.read_text()),result,manifest,a.source_commit)
    response=subprocess.run(['gh','release','view',tag,'--repo',a.repo,'--json','isDraft,url,targetCommitish'],capture_output=True,text=True)
    existed=response.returncode==0
    require(existed or not a.publish_staged,'Staged release is unavailable; refusing to create a replacement')
    if existed:
        require(json.loads(response.stdout)['isDraft'],'Published packed generations are immutable')
        require(json.loads(response.stdout)['targetCommitish']==a.source_commit,'Existing draft targets another builder commit')
        require(tag_commit(a.repo,tag) in (None,a.source_commit),'Existing draft tag belongs to another builder commit')
    notes=a.result.parent/'release-notes.txt'
    status='Physical-device integration and bounded-RSS gates passed.' if a.publish else 'Staged draft; physical-device rollout gates are pending.'
    notes.write_text(f"Packed immutable runtime for {result['region']}; requires YouSpeed 1.6 or newer.\n\n"
        f"Context, exact source geometry and generic sign nodes are verified before activation. Corrections remain in a separate writable store.\n\n"
        f"Installed runtime: {result['packed_installed_bytes']:,} bytes (source {result['source_installed_bytes']:,}). "
        f"Runtime download: {result['packed_download_bytes']:,} bytes (source {result['source_download_bytes']:,}).\n\n"
        f"Builder commit: {a.source_commit}. Legacy V3 release is preserved. {status}\n")
    if not existed:
        run(['release','create',tag,'--repo',a.repo,'--target',a.source_commit,'--draft','--latest=false',
             '--title',result['region']+' packed runtime '+result['bundle_version'],'--notes-file',str(notes)])
        require(tag_commit(a.repo,tag) in (None,a.source_commit),'Created tag differs from builder commit')
    if not a.publish_staged:
        for name in [*sorted(set(assets)-{manifest_name}),manifest_name]:
            run(['release','upload',tag,str(root/name),'--repo',a.repo,'--clobber'])
    remote=json.loads(subprocess.check_output(['gh','api',f'repos/{a.repo}/releases/tags/{tag}'],text=True))
    received={x['name']:x for x in remote['assets']}
    for name,item in assets.items():
        require(received.get(name,{}).get('size')==item['bytes'] and received.get(name,{}).get('digest')=='sha256:'+item['sha256'],'GitHub asset differs: '+name)
    if a.publish:run(['release','edit',tag,'--repo',a.repo,'--draft=false','--latest=false','--notes-file',str(notes)])
    if a.publish:require(tag_commit(a.repo,tag)==a.source_commit,'Published tag differs from builder commit')
    receipt={'release_tag':tag,'url':remote['html_url'],'source_commit':a.source_commit,
             'all_asset_hashes_verified':True,'asset_count':len(assets),'published':a.publish}
    (a.result.parent/'github-verified.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt,indent=2))


if __name__=='__main__':main()
