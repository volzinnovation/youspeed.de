import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('overnight', Path(__file__).parents[2] / 'scripts/tsr/run_fr_end_sign_overnight.py')
night = importlib.util.module_from_spec(spec)
spec.loader.exec_module(night)


class OvernightTests(unittest.TestCase):
    def test_plan_repeats_controlled_comparisons_with_different_seeds(self):
        plan = list(night.experiments())
        self.assertEqual(len(plan), 18)
        self.assertEqual(len({tuple(row.items()) for row in plan}), 18)
        self.assertEqual({row['scope'] for row in plan}, {'full', 'frozen-bn', 'linear'})
        self.assertTrue(all(row['lr'] < 1e-4 for row in plan))
        self.assertEqual([r['scope'] for r in plan[:6]], [r['scope'] for r in plan[6:12]])

    def test_target_improvement_does_not_hide_other_class_regression(self):
        def result(top1, target):
            return {'variants': {v: {'top1_accuracy': top1, 'target': {'macro_f1': target}}
                                 for v in ['clean', 'blur']}}
        report = night.comparison(result(.9966, .98), result(.99, .999))
        self.assertFalse(report['clean_non_regression'])
        self.assertFalse(report['deployment_approved'])
        self.assertGreater(report['clean_target_f1_delta'], 0)
        self.assertLess(report['clean_top1_delta'], 0)
        self.assertTrue(night.comparison(result(.9966, .98), result(.9966, .98))['clean_non_regression'])

if __name__ == '__main__':
    unittest.main()
