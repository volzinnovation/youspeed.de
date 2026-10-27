#!/usr/bin/env python3
"""Build only; deployment is a separately coordinated device action."""
import argparse
import json
from pathlib import Path
import plistlib
import subprocess


def main():
    p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path,required=True);p.add_argument('--team',required=True);a=p.parse_args()
    repo=Path(__file__).resolve().parents[2];out=a.workspace.resolve()/'iphone-project';out.mkdir(parents=True,exist_ok=True)
    sources=[repo/'benchmarks/packed-runtime/iphone/BenchmarkApp.mm',repo/'benchmarks/packed-runtime/packed_benchmark.cpp',repo/'shared/runtime-storage-prototype/runtime_storage.cpp',repo/'shared/runtime-storage-prototype/packed_runtime.cpp',repo/'shared/runtime-storage-prototype/packed_sqlite_vfs.cpp',repo/'shared/runtime-storage-prototype/zstd_decoder.c']
    settings={'PRODUCT_BUNDLE_IDENTIFIER':'de.youspeed.StoragePrototypeBenchmark','DEVELOPMENT_TEAM':a.team,'CODE_SIGN_STYLE':'Automatic','CLANG_CXX_LANGUAGE_STANDARD':'c++17','CLANG_ENABLE_OBJC_ARC':'YES','GCC_OPTIMIZATION_LEVEL':'3','HEADER_SEARCH_PATHS':['$(inherited)',str(repo/'benchmarks/packed-runtime'),str(repo/'shared/runtime-storage-prototype')],'TARGETED_DEVICE_FAMILY':'1','MARKETING_VERSION':'0.2','CURRENT_PROJECT_VERSION':'2','INFOPLIST_FILE':str(out/'Info.plist'),'SDKROOT':'iphoneos','IPHONEOS_DEPLOYMENT_TARGET':'18.0','OTHER_LDFLAGS':['$(inherited)','-lc++']}
    info={'CFBundleIdentifier':'$(PRODUCT_BUNDLE_IDENTIFIER)','CFBundleExecutable':'$(EXECUTABLE_NAME)','CFBundleName':'$(PRODUCT_NAME)','CFBundleDisplayName':'YouSpeed Packed Bench','CFBundlePackageType':'APPL','CFBundleShortVersionString':'0.2','CFBundleVersion':'2','LSRequiresIPhoneOS':True,'UILaunchScreen':{},'UIFileSharingEnabled':True,'LSSupportsOpeningDocumentsInPlace':True,'UISupportedInterfaceOrientations':['UIInterfaceOrientationPortrait']}
    with (out/'Info.plist').open('wb') as f:plistlib.dump(info,f)
    spec={'sources':list(map(str,sources)),'settings':settings};(out/'spec.json').write_text(json.dumps(spec,indent=2)+'\n')
    ruby=r'''
require 'json'
require 'xcodeproj'
spec=JSON.parse(File.read(ARGV[0]));out=ARGV[1]
project=Xcodeproj::Project.new(File.join(out,'PackedRuntimeBenchmark.xcodeproj'))
target=project.new_target(:application,'PackedRuntimeBenchmark',:ios,'18.0')
group=project.main_group.new_group('Sources')
spec.fetch('sources').each{|path| target.source_build_phase.add_file_reference(group.new_file(path))}
['System/Library/Frameworks/UIKit.framework','System/Library/Frameworks/Foundation.framework','System/Library/Frameworks/CoreGraphics.framework','usr/lib/libsqlite3.tbd','usr/lib/libz.tbd'].each{|path| ref=project.frameworks_group.new_file(path);ref.source_tree='SDKROOT';target.frameworks_build_phase.add_file_reference(ref)}
target.build_configurations.each{|build|spec.fetch('settings').each{|key,value|build.build_settings[key]=value}}
project.save;scheme=Xcodeproj::XCScheme.new;scheme.add_build_target(target);scheme.set_launch_target(target);scheme.save_as(File.join(out,'PackedRuntimeBenchmark.xcodeproj'),'PackedRuntimeBenchmark',true)
'''
    subprocess.run(['ruby','-e',ruby,str(out/'spec.json'),str(out)],check=True)
    subprocess.run(['xcodebuild','build','-project',str(out/'PackedRuntimeBenchmark.xcodeproj'),'-scheme','PackedRuntimeBenchmark','-configuration','Release','-destination','generic/platform=iOS','-derivedDataPath',str(a.workspace.resolve()/'iphone-build'),'-allowProvisioningUpdates','-allowProvisioningDeviceRegistration','-quiet'],check=True)


if __name__=='__main__':main()
