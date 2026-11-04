"""Meaningful software gates: known image truth, coordinate signs, invalidation and source identity."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np
from PIL import Image

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from fly01_vision.detector import detect_rgb
from fly01_vision.k230_protocol import make_message, validate_message, transformed_components
from fly01_vision.pipeline import VisionPipeline, transform_rgb
from fly01_vision.project_adapter import build_project_proposal
from fly01_vision.settings import load_settings
from fly01_vision.sources import gif_frames, k230_frames


class VisionTests(unittest.TestCase):
    def setUp(self):
        self.config = load_settings()
        self.rgb = np.array(Image.open(BASE/'samples/images/01_left.png').convert('RGB'))
        self.source = {"kind": "IMAGE_FILE", "capture_time_ns": None,
                       "capture_clock_domain": None, "capture_time_verified": False}

    def run_frame(self, pipeline=None, frame=0, now=100):
        pipeline = pipeline or VisionPipeline(self.config, 'test-session', 'test-clock')
        obs, _ = pipeline.process_rgb(self.rgb, frame_id=frame, source=self.source,
                                      received_ns=0, processed_ns=now)
        return pipeline, obs

    def test_unchanged_eight_fixture_truth(self):
        expected = json.loads((BASE/'samples/BY01_expected_manifest.json').read_text(encoding='utf-8'))
        for row in expected['frames']:
            with self.subTest(frame=row['file']):
                image = np.array(Image.open(BASE/'samples'/row['file']).convert('RGB'))
                got = detect_rgb(image, self.config['detector'])
                for field in ('status', 'object_count', 'bounding_boxes_xyxy_exclusive', 'selected_center_xy'):
                    self.assertEqual(got[field], row['expected'][field])

    def test_normalized_pixel_sign_and_no_fake_geometry(self):
        _, obs = self.run_frame()
        self.assertLess(obs['normalized_offset_xy'][0], 0)
        self.assertAlmostEqual(obs['normalized_offset_xy'][1], 0)
        self.assertIsNone(obs['geometry']['azimuth_rad'])
        self.assertIsNone(obs['geometry']['relative_position_body_m'])
        self.assertTrue(obs['stop_required'])
        self.assertFalse(obs['eligible_for_live_control'])

    def test_preview_mirror_does_not_change_numeric_coordinate(self):
        self.config['input']['preview_mirror_x'] = True
        _, obs = self.run_frame()
        self.assertEqual(obs['selected_center_xy'], [149.5, 239.5])
        self.assertEqual(obs['preview_center_xy'], [489.5, 239.5])
        self.assertLess(obs['normalized_offset_xy'][0], 0)

    def test_sensor_mirror_changes_coordinate(self):
        self.config['input']['sensor_mirror_x'] = True
        _, obs = self.run_frame()
        self.assertEqual(obs['selected_center_xy'], [489.5, 239.5])
        self.assertEqual(obs['image_relation'], 'IMAGE_RIGHT')

    def test_rotation_clockwise(self):
        self.config['input']['rotation_deg'] = 90
        _, obs = self.run_frame()
        self.assertEqual([obs['width'], obs['height']], [480, 640])
        self.assertEqual(obs['selected_center_xy'], [239.5, 149.5])

    def test_single_target_then_absence_clears_old_target(self):
        pipeline, _ = self.run_frame()
        empty = np.full_like(self.rgb, 238)
        absent, _ = pipeline.process_rgb(empty, frame_id=1, source=self.source, received_ns=100, processed_ns=200)
        self.assertEqual(absent['status'], 'NO_TARGET')
        self.assertIsNone(absent['selected_center_xy'])
        self.assertIsNone(pipeline.poll(201, 'test-clock')['selected_center_xy'])

    def test_expiry_is_inclusive_and_cannot_revive_selection(self):
        pipeline, _ = self.run_frame()
        stale = pipeline.poll(250_000_000, 'test-clock')
        self.assertEqual(stale['status'], 'STALE')
        self.assertIsNone(stale['selected_center_xy'])
        self.assertIsNone(pipeline.poll(100, 'test-clock')['selected_center_xy'])

    def test_slow_detection_is_stale(self):
        _, obs = self.run_frame(now=250_000_000)
        self.assertEqual(obs['status'], 'STALE')
        self.assertIsNone(obs['selected_center_xy'])

    def test_duplicate_invalidates_latest_and_does_not_restore(self):
        pipeline, _ = self.run_frame()
        _, obs = self.run_frame(pipeline=pipeline, frame=0)
        self.assertEqual(obs['status'], 'REJECTED')
        self.assertIsNone(pipeline.poll(101, 'test-clock')['selected_center_xy'])

    def test_foreign_poll_clock_invalidates(self):
        pipeline, _ = self.run_frame()
        self.assertEqual(pipeline.poll(200, 'different-clock')['status'], 'ERROR')
        self.assertIsNone(pipeline.poll(201, 'test-clock')['selected_center_xy'])

    def test_eof_invalidation(self):
        pipeline, _ = self.run_frame()
        self.assertEqual(pipeline.ended()['status'], 'INPUT_ENDED')
        self.assertIsNone(pipeline.poll(200, 'test-clock')['selected_center_xy'])
        fresh = VisionPipeline(self.config, 'empty', 'clock')
        self.assertEqual(fresh.ended()['status'], 'INPUT_ENDED')
        self.assertEqual(fresh.poll(10, 'clock')['status'], 'INPUT_ENDED')
        self.assertTrue(fresh.poll(10, 'clock')['stop_required'])

    def test_bad_rgb_or_k230_cannot_leave_previous_target_valid(self):
        for kind in ('RGB', 'K230'):
            pipeline, _ = self.run_frame()
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                if kind == 'RGB':
                    pipeline.process_rgb(np.zeros((3, 3), dtype=np.uint8), frame_id=1,
                        source=self.source, received_ns=101, processed_ns=102)
                else:
                    pipeline.process_k230({'schema': 'BAD'}, frame_id=1,
                        source=self.source, received_ns=101, processed_ns=102)
            result = pipeline.poll(103, 'test-clock')
            self.assertEqual(result['status'], 'ERROR')
            self.assertIsNone(result['selected_center_xy'])
            self.assertTrue(result['stop_required'])
        fresh = VisionPipeline(self.config, 'empty', 'clock')
        with self.assertRaises(ValueError):
            fresh.process_k230({}, frame_id=0, source=self.source, received_ns=0, processed_ns=1)
        self.assertEqual(fresh.poll(2, 'clock')['status'], 'ERROR')

    def test_calibration_angle_sign_is_left_positive_and_range_stays_null(self):
        self.config['calibration'].update(intrinsics_verified=True, rectified_input_verified=True,
            level_mount_verified=True, mounting_verified=True, width_px=640, height_px=480,
            fx_px=500.0, fy_px=500.0, cx_px=319.5, cy_px=239.5, mount_yaw_rad=0.0)
        _, obs = self.run_frame()
        self.assertGreater(obs['geometry']['azimuth_rad'], 0)
        self.assertAlmostEqual(np.linalg.norm(obs['geometry']['unit_ray_body']), 1.0)
        self.assertIsNone(obs['geometry']['relative_position_body_m'])
        proposal = build_project_proposal(obs, 3)
        self.assertEqual(proposal['status'], 'BLOCKED')
        self.assertIsNone(proposal['feedback_frame'])
        self.assertIn('METRIC_GEOMETRY_NOT_VERIFIED', proposal['blocking_reasons'])

    def test_resolution_mismatch_blocks_angle(self):
        self.config['calibration'].update(intrinsics_verified=True, rectified_input_verified=True,
            level_mount_verified=True, mounting_verified=True, width_px=1280, height_px=960,
            fx_px=500.0, fy_px=500.0, cx_px=319.5, cy_px=239.5, mount_yaw_rad=0.0)
        _, obs = self.run_frame()
        self.assertEqual(obs['geometry']['calibration_status'], 'RESOLUTION_MISMATCH')
        self.assertIsNone(obs['geometry']['azimuth_rad'])

    def test_gif_is_replay_and_preserves_all_eight_scenes(self):
        frames = list(gif_frames(BASE/'samples/sequence.gif', 2073600))
        self.assertEqual(len(frames), 8)
        self.assertEqual(frames[0].source['kind'], 'GIF_REPLAY')
        self.assertIsNone(frames[0].source['capture_time_ns'])
        detections = [detect_rgb(f.rgb, self.config['detector']) for f in frames]
        self.assertEqual([d['status'] for d in detections],
            ['VALID', 'VALID', 'VALID', 'NO_TARGET', 'VALID', 'NO_TARGET', 'VALID', 'AMBIGUOUS'])

    def test_k230_replay_does_not_verify_clock_or_live_transport(self):
        frames = list(k230_frames(BASE/'samples/k230_messages.jsonl', 2073600))
        first = frames[0]
        self.assertFalse(first.source['live_transport_verified'])
        self.assertFalse(first.source['capture_time_verified'])
        self.assertEqual(first.source['transport'], 'JSONL_FILE_REPLAY')
        pipeline = VisionPipeline(self.config, 'pc', 'pc-clock')
        obs = pipeline.process_k230(first.k230_record, frame_id=0, source=first.source,
                                    received_ns=0, processed_ns=100)
        self.assertEqual(obs['selected_center_xy'], [149.5, 239.5])
        self.assertEqual(build_project_proposal(obs, 1)['status'], 'BLOCKED')

    def test_k230_coordinate_transforms_match_rgb_for_all_orientations(self):
        components = detect_rgb(self.rgb, self.config['detector'])['components']
        message = make_message('board', 0, 640, 480, components)
        for rotation in (0, 90, 180, 270):
            for mirror in (False, True):
                settings = deepcopy(self.config['input'])
                settings.update(rotation_deg=rotation, sensor_mirror_x=mirror)
                comps, width, height = transformed_components(message, settings, self.config['detector'])
                expected = detect_rgb(transform_rgb(self.rgb, settings), self.config['detector'])
                self.assertEqual(comps[0]['bbox_xyxy_exclusive'], expected['bounding_boxes_xyxy_exclusive'][0])
                self.assertEqual(comps[0]['center_xy'], expected['selected_center_xy'])
                self.assertEqual([width, height], [expected['width'], expected['height']])

    def test_k230_invalid_bounds_nonfinite_and_duplicate_rejected(self):
        record = json.loads((BASE/'samples/k230_messages.jsonl').read_text().splitlines()[0])
        bad = deepcopy(record)
        bad['objects'][0]['center_xy'][0] = float('nan')
        with self.assertRaises(ValueError):
            validate_message(bad)
        bad = deepcopy(record)
        bad['objects'][0]['bbox_xyxy_exclusive'][2] = 10000
        with self.assertRaises(ValueError):
            validate_message(bad)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'repeat.jsonl'
            path.write_text((json.dumps(record)+'\n')*2)
            with self.assertRaises(ValueError):
                list(k230_frames(path, 2073600))
            nonfinite_extra = deepcopy(record)
            nonfinite_extra['origin'] = float('nan')
            path.write_text(json.dumps(nonfinite_extra)+'\n')
            with self.assertRaises(ValueError):
                list(k230_frames(path, 2073600))

    def test_bad_config_rejected(self):
        for override in ({'input': {'sensor_mirror_x': 1}}, {'input': {'rotation_deg': 45}},
                         {'detector': {'minimum_area_px': 0}}, {'freshness': {'max_processing_age_ms': -1}},
                         {'calibration': {'intrinsics_verified': True}}, {'unknown_key': 1}):
            with self.subTest(override=override), tempfile.TemporaryDirectory() as tmp:
                config = Path(tmp)/'bad.json'
                config.write_text(json.dumps(override))
                with self.assertRaises(ValueError):
                    load_settings(config)


if __name__ == '__main__':
    unittest.main()
