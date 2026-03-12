#!/usr/bin/env python3
import pathlib
import sys
import zlib


SQLITE_MAGIC = b"SQLite format 3\x00"


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: inflate_bundled_seed.py <input.zlib> <output.sqlite>")

    source = pathlib.Path(sys.argv[1])
    target = pathlib.Path(sys.argv[2])
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        try:
            if target.stat().st_mtime >= source.stat().st_mtime:
                with target.open("rb") as handle:
                    if handle.read(len(SQLITE_MAGIC)) == SQLITE_MAGIC:
                        return 0
        except OSError:
            pass

    inflated = zlib.decompress(source.read_bytes())
    if not inflated.startswith(SQLITE_MAGIC):
        raise SystemExit("inflated seed does not start with SQLite header")

    tmp = target.with_suffix(f"{target.suffix}.tmp")
    tmp.write_bytes(inflated)
    tmp.replace(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
