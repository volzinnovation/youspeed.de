import copy
import importlib.util
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('fetch_a2d2', Path(__file__).resolve().parents[2] / 'scripts/lanes/fetch_a2d2_subset.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class A2D2FetcherTests(unittest.TestCase):
    def test_dates_are_disjoint_and_old_smoke_dates_are_training(self):
        m.validate_config(m.DEFAULT_CONFIG)
        self.assertTrue({'20180807','20181008'} <= set(m.DEFAULT_CONFIG['split_dates']['train']))
        config = copy.deepcopy(m.DEFAULT_CONFIG)
        config['split_dates']['test'].append('20180807')
        with self.assertRaisesRegex(ValueError,'overlaps'):
            m.validate_config(config)

    def test_budget_cannot_exceed_one_decimal_gigabyte(self):
        config = copy.deepcopy(m.DEFAULT_CONFIG); config['maximum_bytes'] = m.CAP+1
        with self.assertRaises(ValueError):
            m.validate_config(config)

    def test_spacing_must_be_finite_and_positive(self):
        for spacing in (0, float('nan'), float('inf'), True):
            config = copy.deepcopy(m.DEFAULT_CONFIG); config['minimum_spacing_seconds'] = spacing
            with self.assertRaises(ValueError):
                m.validate_config(config)

    def test_dispersed_order_covers_each_index_once(self):
        self.assertEqual(list(m.dispersed_indices(0)), [])
        self.assertEqual(list(m.dispersed_indices(1)), [0])
        self.assertEqual(list(m.dispersed_indices(9))[:5], [0,8,4,2,6])
        for count in range(2,100):
            self.assertEqual(sorted(m.dispersed_indices(count)),list(range(count)))

    def test_object_paths_cannot_escape_output(self):
        for path in ('../source.png','/absolute.png','a/../../x','a\\x'):
            with self.assertRaises(ValueError):
                m.safe_key(path)
        self.assertEqual(m.safe_key('camera_lidar_semantic/a/image.png'),'camera_lidar_semantic/a/image.png')

    def test_png_shape_uses_original_ihdr(self):
        data = b'\x89PNG\r\n\x1a\n'+struct.pack('>I',13)+b'IHDR'+struct.pack('>II',1920,1208)
        self.assertEqual(m.png_dimensions(data),[1920,1208])
        with self.assertRaises(ValueError):
            m.png_dimensions(b'not a png')

    def test_unpaired_publisher_images_are_excluded_before_sampling(self):
        prefix = 'camera_lidar_semantic/20180807_145028/'
        rgb = prefix+'camera/cam_front_center/20180807145028_camera_frontcenter_000000091.png'
        other = prefix+'camera/cam_front_center/20180807145028_camera_frontcenter_000000092.png'
        label = rgb.replace('/camera/','/label/').replace('_camera_','_label_')
        camera_rows = [{'key':k} for k in (rgb,rgb[:-4]+'.json',other,other[:-4]+'.json')]
        with patch.object(m,'listing',side_effect=[(camera_rows,[]),([{'key':label}],[])]):
            _,_,pairs,stats = m.inventory('20180807_145028')
        self.assertEqual([p['rgb'] for p in pairs],[rgb])
        self.assertEqual(stats['excluded_unpaired_rgb'],[other])


if __name__ == '__main__':
    unittest.main()
