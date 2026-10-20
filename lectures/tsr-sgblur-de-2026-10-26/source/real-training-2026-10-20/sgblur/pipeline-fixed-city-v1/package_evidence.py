#!/usr/bin/env python3
"""Package saved fixed pipeline evidence only; no models or inference."""
import hashlib
import json
import zipfile
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    root = Path(__file__).resolve().parent
    audit = root/'pipeline-method-peer-audit.json'
    assert sha(audit) == '5e5a8cbfe4044a723a4317eb17eb6bdb60f9c2631781fb4fd01ef04642c4959e'
    archive = root.parent/'pipeline-fixed-city15-2026-10-20.zip'
    assert not archive.exists(), 'New evidence archive required'
    sources = sorted(p for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name != 'package-inventory.json')
    assert all(not p.is_symlink() for p in sources)
    inventory = {'schema_version': 'fixed-pipeline-delivery-inventory-v1',
                 'scope': 'Single frozen scoring event and analysis-only summaries; actual predicted crops, no source full-HD images or model weights.',
                 'self_excluded_from_file_hashes': True,
                 'files': [{'path': p.relative_to(root).as_posix(), 'bytes': p.stat().st_size, 'sha256': sha(p)} for p in sources]}
    inventory_path = root/'package-inventory.json'
    inventory_path.write_text(json.dumps(inventory, ensure_ascii=False, indent=2)+'\n')
    sources.append(inventory_path)
    archive_root = 'sgblur-tsr-city15-pipeline-2026-10-20'
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
        for source in sorted(sources):
            relative = source.relative_to(root).as_posix()
            assert not relative.startswith('/') and '..' not in Path(relative).parts
            package.write(source, archive_root+'/'+relative)
    with zipfile.ZipFile(archive) as package:
        assert package.testzip() is None
        assert len(package.infolist()) == len(sources)
        for source in sources:
            name = archive_root+'/'+source.relative_to(root).as_posix()
            assert hashlib.sha256(package.read(name)).hexdigest() == sha(source)
    receipt = {'schema_version': 'fixed-pipeline-delivery-receipt-v1',
               'path': archive.name, 'bytes': archive.stat().st_size, 'sha256': sha(archive),
               'files': len(sources), 'uncompressed_bytes': sum(p.stat().st_size for p in sources),
               'zip_crc_verified': True, 'all_file_sha256_verified_after_zip': True,
               'peer_audit_sha256': sha(audit), 'model_weights_included': False, 'source_full_images_included': False,
               'additional_model_inference_performed': False}
    (root.parent/'pipeline-delivery-receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
