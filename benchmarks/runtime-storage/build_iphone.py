#!/usr/bin/env python3
"""Build the isolated benchmark without changing the consumer Xcode project."""
import argparse
import json
import plistlib
from pathlib import Path
import subprocess


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workspace', type=Path, required=True)
    ap.add_argument('--sqlite-source', type=Path, required=True)
    ap.add_argument('--geodesk-library', type=Path, required=True)
    ap.add_argument('--team', required=True)
    args = ap.parse_args()
    repo = Path(__file__).resolve().parents[2]
    output = args.workspace.resolve() / 'iphone-project'
    output.mkdir(parents=True, exist_ok=True)
    sources = [repo / 'benchmarks/runtime-storage/iphone/BenchmarkApp.mm',
               repo / 'shared/runtime-storage-prototype/runtime_storage.cpp',
               repo / 'shared/runtime-corrections-prototype/runtime_corrections.cpp',
               repo / 'shared/runtime-sign-nodes-prototype/runtime_sign_nodes.cpp',
               args.sqlite_source.resolve() / 'sqlite3.c']
    spec = {
        'name': 'StoragePrototypeBenchmark',
        'options': {'deploymentTarget': {'iOS': '18.0'}, 'createIntermediateGroups': True},
        'targets': {'StoragePrototypeBenchmark': {
            'type': 'application', 'platform': 'iOS',
            'sources': [{'path': str(p)} for p in sources],
            'settings': {'base': {
                'PRODUCT_BUNDLE_IDENTIFIER': 'de.youspeed.StoragePrototypeBenchmark',
                'DEVELOPMENT_TEAM': args.team, 'CODE_SIGN_STYLE': 'Automatic',
                'CLANG_CXX_LANGUAGE_STANDARD': 'c++17', 'CLANG_ENABLE_OBJC_ARC': 'YES',
                'GCC_OPTIMIZATION_LEVEL': '3', 'SWIFT_VERSION': '5.0',
                'HEADER_SEARCH_PATHS': [str(args.sqlite_source.resolve()),
                    str(repo / 'shared/runtime-storage-prototype'), str(repo / 'shared/runtime-storage-geodesk')],
                'LIBRARY_SEARCH_PATHS': ['$(inherited)', str(args.geodesk_library.resolve().parent)],
                'GCC_PREPROCESSOR_DEFINITIONS': ['$(inherited)', 'YSP_WITH_GEODESK=1',
                    'SQLITE_ENABLE_RTREE=1', 'SQLITE_OMIT_LOAD_EXTENSION=1', 'SQLITE_THREADSAFE=1'],
                'TARGETED_DEVICE_FAMILY': '1',
                'MARKETING_VERSION': '0.1', 'CURRENT_PROJECT_VERSION': '1',
            }},
            'dependencies': [{'framework': str(args.geodesk_library.resolve()), 'embed': False},
                             {'sdk': 'libz.tbd'}],
            'info': {'path': str(output / 'Info.plist'), 'properties': {
                'CFBundleDisplayName': 'YouSpeed Storage Bench',
                'UILaunchScreen': {},
                'UIFileSharingEnabled': True, 'LSSupportsOpeningDocumentsInPlace': True,
                'UISupportedInterfaceOrientations': ['UIInterfaceOrientationPortrait'],
            }},
        }},
        'schemes': {'StoragePrototypeBenchmark': {
            'build': {'targets': {'StoragePrototypeBenchmark': 'all'}},
            'run': {'config': 'Release'},
        }},
    }
    spec_path = output / 'project.yml'
    spec_path.write_text(json.dumps(spec, indent=2) + '\n')
    # Xcodeproj avoids altering or regenerating the consumer application project.
    plist = dict(spec['targets']['StoragePrototypeBenchmark']['info']['properties'])
    plist.update({'CFBundleIdentifier': '$(PRODUCT_BUNDLE_IDENTIFIER)',
                  'CFBundleExecutable': '$(EXECUTABLE_NAME)', 'CFBundleName': '$(PRODUCT_NAME)',
                  'CFBundlePackageType': 'APPL', 'CFBundleShortVersionString': '0.1',
                  'CFBundleVersion': '1', 'LSRequiresIPhoneOS': True})
    with (output / 'Info.plist').open('wb') as target:
        plistlib.dump(plist, target)
    ruby = r'''
require 'json'
require 'xcodeproj'
spec = JSON.parse(File.read(ARGV[0]))
out = ARGV[1]
project = Xcodeproj::Project.new(File.join(out, 'StoragePrototypeBenchmark.xcodeproj'))
target = project.new_target(:application, 'StoragePrototypeBenchmark', :ios, '18.0')
config = spec.fetch('targets').fetch('StoragePrototypeBenchmark')
group = project.main_group.new_group('Sources')
config.fetch('sources').each do |source|
  ref = group.new_file(source.fetch('path'))
  target.source_build_phase.add_file_reference(ref)
end
library = project.frameworks_group.new_file(config.fetch('dependencies')[0].fetch('framework'))
target.frameworks_build_phase.add_file_reference(library)
['System/Library/Frameworks/UIKit.framework', 'System/Library/Frameworks/Foundation.framework', 'System/Library/Frameworks/CoreGraphics.framework', 'usr/lib/libz.tbd'].each do |path|
  ref = project.frameworks_group.new_file(path)
  ref.source_tree = 'SDKROOT'
  target.frameworks_build_phase.add_file_reference(ref)
end
target.build_configurations.each do |build|
  config.fetch('settings').fetch('base').each { |key, value| build.build_settings[key] = value }
  build.build_settings['INFOPLIST_FILE'] = File.join(out, 'Info.plist')
  build.build_settings['SDKROOT'] = 'iphoneos'
  build.build_settings['IPHONEOS_DEPLOYMENT_TARGET'] = '18.0'
  build.build_settings['OTHER_LDFLAGS'] = ['$(inherited)', '-lc++']
end
project.save
scheme = Xcodeproj::XCScheme.new
scheme.add_build_target(target)
scheme.set_launch_target(target)
scheme.save_as(File.join(out, 'StoragePrototypeBenchmark.xcodeproj'), 'StoragePrototypeBenchmark', true)
'''
    subprocess.run(['ruby', '-e', ruby, str(spec_path), str(output)], check=True)
    subprocess.run(['xcodebuild', 'build', '-project', str(output / 'StoragePrototypeBenchmark.xcodeproj'),
                    '-scheme', 'StoragePrototypeBenchmark', '-configuration', 'Release',
                    '-destination', 'generic/platform=iOS', '-derivedDataPath', str(args.workspace.resolve() / 'iphone-build'),
                    '-allowProvisioningUpdates', '-allowProvisioningDeviceRegistration', '-quiet'], check=True)


if __name__ == '__main__':
    main()
