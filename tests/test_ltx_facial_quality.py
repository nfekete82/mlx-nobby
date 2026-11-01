"""CPU diagnostics regressions; image-venv/bin/python -m unittest."""
import importlib.util
from pathlib import Path
import tempfile
import json
import sys
from types import SimpleNamespace
from unittest import mock
import unittest

try:
    import numpy as np
    import scipy.ndimage
except ImportError as error:
    raise unittest.SkipTest('Requires existing image-venv NumPy/SciPy') from error

spec=importlib.util.spec_from_file_location('facial',Path(__file__).resolve().parents[1]/'scripts/benchmark-ltx-facial-quality.py')
facial=importlib.util.module_from_spec(spec)
spec.loader.exec_module(facial)


class FacialQualityTests(unittest.TestCase):
    def test_lab_d65_reference_and_color_changes(self):
        np.testing.assert_allclose(facial.lab_d65([0,0,0]),[0,0,0],atol=1e-5)
        np.testing.assert_allclose(facial.lab_d65([255,255,255]),[100,0,0],atol=.001)
        self.assertGreater(np.linalg.norm(facial.lab_d65([200,100,80])-facial.lab_d65([190,95,75])),1)

    def test_registration_removes_translation_and_rejects_unreliable_data(self):
        a=np.random.default_rng(7).integers(0,256,(128,128),dtype=np.uint8)
        result=facial.registered_change(a,np.roll(a,(3,-2),axis=(0,1)))
        self.assertEqual(result['status'],'measured')
        self.assertEqual(result['shift_yx'],[-3,2])
        self.assertAlmostEqual(result['registered_luma_mae'],0)
        self.assertGreater(result['raw_luma_mae'],10)
        self.assertEqual(facial.registered_change(a,np.roll(a,20,axis=0))['status'],'registration_uncertain')
        self.assertEqual(facial.registered_change(a*0,a*0)['status'],'insufficient_texture')

    def test_missing_low_confidence_and_closed_eye_are_not_reliable_pupils(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            facial.Image.new('RGB',(100,100),(180,130,100)).save(root/'frame.png')
            face={'confidence':.99,'bounding_box':[10,10,80,80], 'landmarks':{
                'leftEye':[[.2,.6],[.3,.6],[.3,.601],[.2,.601]],
                'rightEye':[[.6,.6],[.7,.6],[.7,.601],[.6,.601]],
                'leftPupil':[[.25,.60]],'rightPupil':[[.65,.60]]}}
            geometry={'samples':[{'frame':0,'image':'frame.png','faces':[face]},
              {'frame':1,'faces':[]},{'frame':2,'faces':[dict(face,confidence=.2)]},
              {'frame':3,'image':'frame.png','faces':[face]}]}
            rows=facial.face_features(root,geometry)
            self.assertFalse(rows[0]['left_pupil_observation_eligible'])
            self.assertNotIn('motion_registered_change',rows[3])
            self.assertEqual(facial.summarize_features(rows)['uncertain_frames'],[1,2])

    def test_native_worker_exports_pngs_and_frees_encoder_before_decoder(self):
        spec=importlib.util.spec_from_file_location('probe',Path(__file__).resolve().parents[1]/'scripts/probe-ltx-vae-reconstruction.py')
        probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)
        order=[]
        class NoClipArray(np.ndarray):
            def clip(self,*a,**kw):raise AttributeError('MLX arrays have no clip method')
        pixels=np.zeros((1,3,4,4),dtype=np.float32).view(NoClipArray)
        core=SimpleNamespace(float32=np.float32,clip=lambda a,lo,hi:np.clip(np.asarray(a),lo,hi),
            eval=lambda *a:None,get_peak_memory=lambda:1024)
        class Conditioner:
            default_image_crf=18
            def __init__(self,*a):pass
            def load(self):
                order.append('encoder_load')
                return SimpleNamespace(encode=lambda a:np.zeros((1,128,1,1,1),dtype=np.float32))
            def free(self):order.append('encoder_free')
        class Decoder:
            def __init__(self,*a,**kw):assert kw['video_decoder']=='conv'
            def load(self):
                order.append('decoder_load')
                return SimpleNamespace(decode=lambda a:pixels[:,:,None])
            def free(self):order.append('decoder_free')
        modules={'mlx':SimpleNamespace(core=core),'mlx.core':core,
          'ltx_pipelines_mlx.utils.blocks':SimpleNamespace(ImageConditioner=Conditioner,VideoDecoder=Decoder),
          'ltx_pipelines_mlx.utils.media_io':SimpleNamespace(load_image_and_preprocess=lambda *a,**kw:pixels),
          'ltx_core_mlx.utils.memory':SimpleNamespace(aggressive_cleanup=lambda:None)}
        with tempfile.TemporaryDirectory() as tmp,mock.patch.dict(sys.modules,modules):
            root=Path(tmp)
            probe.worker(SimpleNamespace(model=root,image=root/'prepared.png',stage='full',out=root))
            self.assertTrue((root/'input.png').exists())
            self.assertTrue((root/'reconstruction.png').exists())
            self.assertEqual(json.loads((root/'reconstruction.json').read_text())['rgb_mae'],0)
        self.assertEqual(order,['encoder_load','encoder_free','decoder_load','decoder_free'])

    def test_timeline_keeps_gaps_and_escapes_labels(self):
        svg=facial.graph([{'frame':0,'eye':1},{'frame':1},{'frame':2,'eye':.5}],['eye'],['red'],'eye <unknown>')
        self.assertIn('&lt;unknown&gt;',svg)
        self.assertIn('M45.00,',svg)
        self.assertIn(' M50.33,',svg)
        self.assertNotIn(' L50.33,',svg)
        self.assertIn('6s',svg)


if __name__=='__main__':unittest.main()
