"""CPU image diagnostics: rotate eyes without introducing fake aperture changes."""
import importlib.util
from pathlib import Path
import unittest

try:
    import numpy as np
    import scipy.ndimage
except ImportError as error:
    raise unittest.SkipTest('Use image-venv for NumPy/SciPy diagnostics') from error

spec=importlib.util.spec_from_file_location('segments',Path(__file__).resolve().parents[1]/'scripts/analyze-ltx-face-segments.py')
segments=importlib.util.module_from_spec(spec);spec.loader.exec_module(segments)


class FaceSegmentTests(unittest.TestCase):
    def face(self,angle):
        theta=np.deg2rad(angle);rotation=np.array([[np.cos(theta),-np.sin(theta)],[np.sin(theta),np.cos(theta)]])
        landmarks={'leftEye':[[.2,.5],[.3,.5],[.3,.53],[.2,.53]],
                   'rightEye':[[.6,.5],[.7,.5],[.7,.53],[.6,.53]],
                   'leftPupil':[[.25,.515]],'rightPupil':[[.65,.515]]}
        return {'bounding_box':[0,0,100,100], 'landmarks':{k:((np.array(v)-.5)@rotation.T+.5).tolist() for k,v in landmarks.items()}}

    def test_eye_aperture_and_pupil_offsets_do_not_confuse_head_roll(self):
        base=segments.eye_observations(self.face(0))
        rotated=segments.eye_observations(self.face(35))
        for eye in ('left','right'):
            self.assertAlmostEqual(base[eye+'_eye_open_ratio'],.3)
            self.assertAlmostEqual(rotated[eye+'_eye_open_ratio'],.3)
            np.testing.assert_allclose(rotated[eye+'_pupil_relative_to_eye'],base[eye+'_pupil_relative_to_eye'],atol=1e-10)

    def test_segment_owns_initial_inclusive_frame_and_closure_is_only_candidate(self):
        rows=[{'frame':i,'face_count':1,'left_eye_open_ratio':.1 if 24<=i<=64 else .3,
               'right_eye_open_ratio':.1 if 24<=i<=64 else .3} for i in range(241)]
        result=segments.segment_summary(rows,0,145)
        self.assertEqual(result['frames'],145)
        self.assertEqual(result['last_frame'],144)
        self.assertEqual(result['bilateral_low_aperture_candidates'][0]['frames'],41)
        self.assertAlmostEqual(result['bilateral_low_aperture_candidates'][0]['duration_seconds'],41/24)
        self.assertEqual(segments.segment_summary(rows,145,193)['frames'],48)
        self.assertEqual(segments.segment_summary(rows,193,241)['frames'],48)


if __name__=='__main__':unittest.main()
