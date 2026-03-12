#!/usr/bin/env python3
"""Apply one or more OSM change files to a local seed PBF."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

import osmium


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply .osc/.osc.gz change files to an OSM PBF")
    parser.add_argument("--input-pbf", required=True, help="Base OSM PBF")
    parser.add_argument(
        "--diff-file",
        dest="diff_files",
        action="append",
        required=True,
        help="Change file (.osc or .osc.gz). May be passed multiple times.",
    )
    parser.add_argument("--output-pbf", required=True, help="Updated OSM PBF output path")
    parser.add_argument("--replication-base-url", default="", help="Optional replication base URL to write into the output header")
    parser.add_argument("--replication-sequence-number", default="", help="Optional replication sequence number to write into the output header")
    parser.add_argument("--replication-timestamp", default="", help="Optional replication timestamp (UTC ISO8601) to write into the output header")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite output path if it already exists")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_pbf = Path(args.input_pbf)
    output_pbf = Path(args.output_pbf)
    diff_files = [Path(path) for path in args.diff_files]

    if not input_pbf.exists():
        raise SystemExit(f"Missing input PBF: {input_pbf}")
    missing_diff = [str(path) for path in diff_files if not path.exists()]
    if missing_diff:
        raise SystemExit(f"Missing diff file(s): {', '.join(missing_diff)}")
    if output_pbf.exists() and not args.overwrite:
        raise SystemExit(f"Output already exists: {output_pbf} (pass --overwrite to replace it)")

    output_pbf.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="apply-osc-") as tmpdir:
        tmp_output = Path(tmpdir) / output_pbf.name
        with osmium.io.Reader(str(input_pbf)) as reader:
            header = reader.header()
            if args.replication_base_url:
                header.set("osmosis_replication_base_url", args.replication_base_url)
            if args.replication_sequence_number:
                header.set("osmosis_replication_sequence_number", args.replication_sequence_number)
            if args.replication_timestamp:
                header.set("osmosis_replication_timestamp", args.replication_timestamp)

            merger = osmium.MergeInputReader()
            for diff_file in diff_files:
                merger.add_file(str(diff_file))

            writer = osmium.io.Writer(str(tmp_output), header=header, overwrite=True)
            try:
                merger.apply_to_reader(reader, writer)
            finally:
                writer.close()

        if output_pbf.exists():
            output_pbf.unlink()
        shutil.move(os.fspath(tmp_output), os.fspath(output_pbf))

    return 0


if __name__ == "__main__":
    sys.exit(main())
