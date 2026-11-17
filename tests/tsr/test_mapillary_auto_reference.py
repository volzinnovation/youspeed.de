import sys,unittest,base64
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts/tsr/sign_only_pilot'))
import mapbox_vector_tile
from mapillary_auto_sample import decode_boxes,reference_scope
class MapillaryReferenceTests(unittest.TestCase):
    def test_pixel_origin_and_anisotropic_scaling(self):
        value=mapbox_vector_tile.encode({'name':'mpy-or','features':[{'geometry':{'type':'Polygon','coordinates':[[[100,200],[300,200],[300,400],[100,400],[100,200]]]},'properties':{}}]},default_options={'y_coord_down':True,'extents':1000})
        box=decode_boxes(base64.b64encode(value).decode(),2000,1000)[0]
        self.assertEqual(box,[200,200,600,400])
    def test_scope_never_certifies_generic_front(self):
        self.assertEqual(reference_scope('object--traffic-sign--front'),'generic_front_scope_unknown')
        self.assertEqual(reference_scope('information--end-of-built-up-area--g3'),'classified_primary_candidate')
        self.assertTrue(reference_scope('information--general-directions--g1').startswith('excluded'))
        self.assertEqual(reference_scope('complementary--distance--g1'),'excluded_supplementary')
if __name__=='__main__':unittest.main()
