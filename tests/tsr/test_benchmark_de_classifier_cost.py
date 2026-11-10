import importlib.util
from pathlib import Path
import tempfile
import unittest


spec = importlib.util.spec_from_file_location(
    "de_classifier_cost", Path(__file__).parents[2] / "scripts/tsr/benchmark_de_classifier_cost.py"
)
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class ClassifierCostTests(unittest.TestCase):
    def test_depthwise_macs_do_not_count_dense_connections(self):
        # 32 depthwise filters on 112x112 pixels, followed by 32->64 pointwise.
        depthwise = benchmark.conv_macs(32 * 112 * 112, 32, 32, (3, 3))
        pointwise = benchmark.conv_macs(64 * 112 * 112, 32, 1, (1, 1))
        self.assertEqual(depthwise, 3_612_672)
        self.assertEqual(pointwise, 25_690_112)
        self.assertEqual(benchmark.conv_macs(100, 8, 2, (3, 3)), 3600)
        with self.assertRaises(ValueError):
            benchmark.conv_macs(100, 8, 3, (3, 3))

    def test_head_macs_preserve_small_extension_cost(self):
        self.assertEqual(benchmark.linear_macs(136, 1280) - benchmark.linear_macs(134, 1280), 2560)

    def test_percentiles_keep_tail_and_reject_invalid_measurements(self):
        result = benchmark.latency_summary([1, 2, 3, 4, 100])
        self.assertEqual(result["p50_ms"], 3)
        self.assertAlmostEqual(result["p95_ms"], 80.8)
        self.assertEqual(result["samples"], 5)
        for values in ([], [float("nan")], [-1], [float("inf")]):
            with self.assertRaises(ValueError):
                benchmark.latency_summary(values)

    def test_hash_mismatch_rejected_before_runtime_imports(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wrong.pt"
            path.write_bytes(b"not the pinned model")
            args = benchmark.parse_args(["--model", str(path), "--output", str(path.with_suffix(".json"))])
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                benchmark.run(args)

    def test_cli_defaults_and_invalid_configuration(self):
        common = ["--model", "original.pt", "--output", "cost.json"]
        args = benchmark.parse_args(common)
        self.assertEqual((args.warmup, args.iterations, args.cpu_threads), (20, 100, [1, 4]))
        self.assertEqual(benchmark.parse_args(common + ["--device", "cuda:1"]).device, "cuda:1")
        for extra in (["--warmup", "0"], ["--iterations", "1"], ["--cpu-threads", "0"],
                      ["--device", "mps"], ["--device", "cuda:bad"]):
            with self.assertRaises(SystemExit):
                benchmark.parse_args(common + extra)


if __name__ == "__main__":
    unittest.main()
