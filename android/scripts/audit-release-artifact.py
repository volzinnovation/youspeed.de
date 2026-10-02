#!/usr/bin/env python3
"""Inspect packaged native libraries without executing or extracting the archive.

A static check cannot establish native runtime behavior. Run the packaged
recognition/speech/camera flows on a real 16 KB runtime before release.
"""
import argparse
import hashlib
import json
import pathlib
import struct
import sys
import zipfile

PAGE_SIZE = 16384
ABIS_64 = {"arm64-v8a", "x86_64"}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def elf_segments(data):
    if data[:4] != b"\x7fELF" or data[4] not in (1, 2) or data[5] not in (1, 2):
        raise ValueError("Native library does not have a supported ELF header")
    endian = "<" if data[5] == 1 else ">"
    if data[4] == 2:
        offset = struct.unpack_from(endian + "Q", data, 32)[0]
        entry_size, count = struct.unpack_from(endian + "HH", data, 54)
        format_string = endian + "IIQQQQQQ"
        entries = [struct.unpack_from(format_string, data, offset + i * entry_size) for i in range(count)]
        return [{"type": e[0], "offset": e[2], "vaddr": e[3], "memsz": e[6], "align": e[7]} for e in entries]
    offset = struct.unpack_from(endian + "I", data, 28)[0]
    entry_size, count = struct.unpack_from(endian + "HH", data, 42)
    format_string = endian + "IIIIIIII"
    entries = [struct.unpack_from(format_string, data, offset + i * entry_size) for i in range(count)]
    return [{"type": e[0], "offset": e[1], "vaddr": e[2], "memsz": e[5], "align": e[7]} for e in entries]


def inspect(path):
    with zipfile.ZipFile(path) as archive:
        libraries = []
        for info in archive.infolist():
            parts = info.filename.split("/")
            if not info.filename.endswith(".so") or "lib" not in parts:
                continue
            abi = parts[parts.index("lib") + 1]
            data = archive.read(info)
            segments = elf_segments(data)
            loads = [s for s in segments if s["type"] == 1]
            relro = [s for s in segments if s["type"] == 0x6474E552]
            load_aligned = bool(loads) and all(s["align"] >= PAGE_SIZE and (s["vaddr"] - s["offset"]) % PAGE_SIZE == 0 for s in loads)
            relro_aligned = all((s["vaddr"] + s["memsz"]) % PAGE_SIZE == 0 for s in relro)
            libraries.append({
                "path": info.filename, "abi": abi, "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "load_alignment_bytes": sorted({s["align"] for s in loads}),
                "load_16k_aligned": load_aligned,
                "relro_end_modulo_16k": [(s["vaddr"] + s["memsz"]) % PAGE_SIZE for s in relro],
                "relro_16k_aligned": relro_aligned,
            })
        native_64 = [lib for lib in libraries if lib["abi"] in ABIS_64]
        signatures = [name for name in archive.namelist() if name.startswith("META-INF/") and name.upper().endswith((".RSA", ".DSA", ".EC"))]
        return {
            "artifact": str(path.resolve()), "bytes": path.stat().st_size, "sha256": sha256(path),
            "zip_entry_compressed_bytes": sum(info.compress_size for info in archive.infolist()),
            "jar_signature_present": bool(signatures),
            "note": "JAR signature presence is not certificate verification. AAB/ZIP byte size is not Play device download size.",
            "native_libraries": libraries,
            "native_64_count": len(native_64),
            "native_64_load_16k_pass": bool(native_64) and all(lib["load_16k_aligned"] for lib in native_64),
            "native_64_relro_16k_pass": bool(native_64) and all(lib["relro_16k_aligned"] for lib in native_64),
            "runtime_16k_verified": False,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=pathlib.Path)
    parser.add_argument("--output", type=pathlib.Path)
    parser.add_argument("--require-16k", action="store_true", help="Fail if any packaged 64-bit LOAD or RELRO alignment check fails")
    args = parser.parse_args()
    report = inspect(args.artifact)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    else:
        sys.stdout.write(rendered)
    if args.require_16k and not (report["native_64_load_16k_pass"] and report["native_64_relro_16k_pass"]):
        print("Packaged 64-bit native libraries need 16 KB compatibility remediation; see audit report.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
