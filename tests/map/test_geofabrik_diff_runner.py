import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "scripts/map/update_from_geofabrik_diffs.sh"


def run_cmd(args, *, env=None, check=True):
    return subprocess.run(args, check=check, text=True, capture_output=True, env=env)


class GeofabrikDiffRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir_ctx = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self.tmpdir_ctx.name)

        self.input_pbf = self.tmpdir / "germany-latest.osm.pbf"
        self.input_pbf.write_bytes(b"dummy pbf payload\n")

        self.work_dir = self.tmpdir / "work"
        self.work_dir.mkdir(parents=True, exist_ok=True)

        self.updates_dir = self.tmpdir / "updates"
        self.updates_dir.mkdir(parents=True, exist_ok=True)
        (self.updates_dir / "state.txt").write_text(
            "sequenceNumber=101\ntimestamp=2026-02-23T11\\:00\\:00Z\n", encoding="utf-8"
        )

        self.state_file = self.tmpdir / "runner_state.json"
        self.state_file.write_text(
            json.dumps(
                {
                    "last_applied_seq": 100,
                    "last_applied_timestamp": "2026-02-23T10:00:00Z",
                    "last_updates_url": f"file://{self.updates_dir}/",
                }
            ),
            encoding="utf-8",
        )

        self.report_path = self.tmpdir / "report.json"

        self.bin_dir = self.tmpdir / "bin"
        self.bin_dir.mkdir(parents=True, exist_ok=True)
        self._write_stubs()

        self.env = os.environ.copy()
        self.env["PATH"] = f"{self.bin_dir}:{self.env['PATH']}"

    def tearDown(self):
        self.tmpdir_ctx.cleanup()

    def _write_executable(self, path: Path, content: str):
        path.write_text(content, encoding="utf-8")
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR)

    def _write_stubs(self):
        update_stub = textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            out=""
            args=("$@")
            i=0
            while [[ $i -lt ${#args[@]} ]]; do
              if [[ "${args[$i]}" == "--outfile" ]]; then
                i=$((i + 1))
                out="${args[$i]}"
              fi
              i=$((i + 1))
            done
            in="${args[$((${#args[@]} - 1))]}"
            if [[ -z "$out" ]]; then
              echo "missing --outfile" >&2
              exit 2
            fi
            cp "$in" "$out"
            """
        )
        self._write_executable(self.bin_dir / "pyosmium-up-to-date", update_stub)

        changes_stub = textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            out=""
            args=("$@")
            i=0
            while [[ $i -lt ${#args[@]} ]]; do
              if [[ "${args[$i]}" == "--outfile" ]]; then
                i=$((i + 1))
                out="${args[$i]}"
              fi
              i=$((i + 1))
            done
            if [[ -z "$out" ]]; then
              echo "missing --outfile" >&2
              exit 2
            fi
            python3 - "$out" <<'PY'
import gzip
import sys

payload = (
    "<osmChange version='0.6' generator='stub'>\\n"
    "<create>\\n"
    "  <node id='1' lat='0.0' lon='0.0'/>\\n"
    "</create>\\n"
    "<modify>\\n"
    "  <way id='2'/>\\n"
    "</modify>\\n"
    "<delete>\\n"
    "  <relation id='3'/>\\n"
    "</delete>\\n"
    "</osmChange>\\n"
)
with gzip.open(sys.argv[1], "wt", encoding="utf-8") as fh:
    fh.write(payload)
print("102")
PY
            """
        )
        self._write_executable(self.bin_dir / "pyosmium-get-changes", changes_stub)

    def test_help(self):
        result = run_cmd([str(RUNNER), "--help"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("--input-pbf", result.stdout)
        self.assertIn("--emit-delta", result.stdout)

    def test_updates_with_delta_export_and_writes_report(self):
        updates_url = f"file://{self.updates_dir}/"
        result = run_cmd(
            [
                str(RUNNER),
                "--region",
                "germany",
                "--input-pbf",
                str(self.input_pbf),
                "--updates-url",
                updates_url,
                "--state-file",
                str(self.state_file),
                "--report-path",
                str(self.report_path),
                "--work-dir",
                str(self.work_dir),
                "--emit-delta",
            ],
            env=self.env,
        )

        self.assertEqual(result.returncode, 0)
        self.assertTrue(self.report_path.exists())

        report = json.loads(self.report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["sequence_delta"], 1)
        self.assertEqual(report["delta_export"]["status"], "exported")

        delta_path = Path(report["delta_export"]["path"])
        self.assertTrue(delta_path.exists())
        self.assertEqual(report["delta_export"]["counts"]["total_entities"], 3)
        self.assertEqual(report["delta_export"]["counts"]["node_count"], 1)
        self.assertEqual(report["delta_export"]["counts"]["way_count"], 1)
        self.assertEqual(report["delta_export"]["counts"]["relation_count"], 1)

        state_payload = json.loads(self.state_file.read_text(encoding="utf-8"))
        self.assertEqual(state_payload["last_applied_seq"], 101)
        self.assertEqual(state_payload["last_run_status"], "ok")
        self.assertEqual(state_payload["last_updates_url"], updates_url)


if __name__ == "__main__":
    unittest.main()
