"""CPU diagnostics contract; run with image-venv/bin/python (unittest)."""
import importlib.util
import json
from unittest import mock
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

try:
    import numpy as np
    import scipy.ndimage
except ImportError as error:
    raise unittest.SkipTest("Run benchmark tests with image-venv/bin/python (NumPy/SciPy)") from error

SPEC = importlib.util.spec_from_file_location('video_quality', Path(__file__).resolve().parents[1] / 'scripts/benchmark-video-quality.py')
quality = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(quality)


class QualityMetricsTests(unittest.TestCase):
    def test_ssim_identical_and_changed_geometry(self):
        a = np.random.default_rng(4).integers(0,256,(64,64),dtype=np.uint8)
        self.assertAlmostEqual(quality.ssim(a,a),1.0,places=6)
        self.assertLess(quality.ssim(a,np.roll(a,5,axis=0)),0.1)
        self.assertEqual(quality.sharpness(np.zeros_like(a)),0)
        self.assertGreater(quality.sharpness(a),100)

    def test_cpu_face_geometry_corrects_box_aspect_and_exports_native_crops(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            quality.Image.new('RGB',(100,200),'white').save(root/'frame.png')
            face={'bounding_box':[10,20,80,100], 'landmarks':{
                'leftEye':[[.2,.6],[.3,.6],[.3,.7],[.2,.7]],
                'rightEye':[[.6,.6],[.7,.6],[.7,.7],[.6,.7]]}}
            frames=[{'frame':0,'time':0,'image':'frame.png'}]
            with mock.patch.object(quality,'run',return_value=json.dumps([{'faces':[face]}]).encode()):
                result=quality.face_geometry(Path('/mock/vision'),root,frames)
            sample=result['samples'][0]
            self.assertAlmostEqual(sample['interocular_over_face_width'],.4)
            self.assertAlmostEqual(sample['left_eye_height_over_width'],1.25)
            self.assertTrue(result['face_crops_available'])
            self.assertTrue((root/'face-000.png').exists())
            self.assertIn('No identity',result['limitations'])

    def test_optional_vision_failure_remains_explicit(self):
        with mock.patch.object(quality,'run',side_effect=OSError('unavailable')):
            result=quality.face_geometry(Path('/missing/vision'),Path('/tmp'),[])
        self.assertEqual(result['status'],'unavailable')

    @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg required')
    def test_real_clip_pts_duplicates_boundaries_and_native_review_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            clip=root/'static.mp4'
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=blue:s=64x128:r=24',
                '-f','lavfi','-i','sine=frequency=440:sample_rate=48000',
                '-t',str(241/24),'-c:v','libx264','-c:a','aac',str(clip)],check=True)
            result=quality.benchmark('static',clip,root)
            self.assertEqual(result['technical']['frames'],241)
            self.assertEqual(result['technical']['pts_anomalies'],[])
            self.assertEqual(result['metrics']['exact_duplicate_frames'],list(range(1,241)))
            self.assertAlmostEqual(result['metrics']['adjacent_ssim']['median'],1.0,places=6)
            self.assertEqual([b['frame'] for b in result['metrics']['boundaries']],[145,193])
            self.assertEqual(result['face_geometry']['status'],'not_measured')
            self.assertTrue((root/'static/frame-145.png').is_file())
            self.assertLess(abs(result['technical']['av_end_offset_seconds']),.025)
            report=quality.write_report(root,[result])
            self.assertEqual(report['videos'][0]['visual_assessment']['identity'],'unmeasured')
            self.assertTrue((root/'index.html').is_file())


if __name__=='__main__':
    unittest.main()
