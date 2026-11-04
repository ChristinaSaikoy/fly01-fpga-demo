"""接入提案的安全边界测试，无硬件或冻结编码器依赖。"""
import math
import unittest
from copy import deepcopy
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fly01_vision.project_adapter import build_project_proposal


def valid_observation():
    return {
        "schema_version": "BY02_VISION_OBSERVATION_V1",
        "session_id": "test-session", "frame_id": 500,
        "status": "VALID", "object_count": 1,
        "width": 320, "height": 240, "selected_center_xy": [80, 120],
        "normalized_offset_xy": [-0.5, 0.0],
        "eligible_for_live_control": True,
        "source": {
            "kind": "CAMERA", "capture_time_verified": True,
            "capture_time_ns": 1234, "capture_clock_domain": "verified-camera-clock",
        },
        "geometry": {
            "calibration_status": "CALIBRATED", "direction_calibrated": True,
            "mounting_verified": True, "metric_geometry_verified": True,
            "relative_position_body_m": [2.0, 1.0, 0.0],
            "azimuth_rad": math.atan2(1.0, 2.0), "unit_ray_body": None,
        },
    }


class ProjectAdapterTests(unittest.TestCase):
    def test_default_is_blocked_without_inventing_geometry(self):
        obs = valid_observation()
        obs["geometry"] = {"calibration_status": "UNCONFIRMED", "azimuth_rad": None,
                           "relative_position_body_m": None, "unit_ray_body": None}
        result = build_project_proposal(obs)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIsNone(result["feedback_frame"])
        obj = result["candidate_feedback_fields"]["objects"][0]
        self.assertIsNone(obj["azimuth_rad"])
        self.assertIsNone(obj["relative_position_body"])
        self.assertIsNone(result["source_drive"])

    def test_ready_is_only_review_and_does_not_use_visual_frame_id(self):
        result = build_project_proposal(valid_observation(), 9)
        self.assertEqual(result["status"], "READY_FOR_INTEGRATION_REVIEW")
        self.assertEqual(result["feedback_frame"]["frame_id"], 8)
        self.assertEqual(result["source_observation"]["frame_id"], 500)
        self.assertEqual(result["feedback_frame"]["objects"][0]["left_right_relation"], "LEFT")
        self.assertFalse(result["transport_performed"])

    def test_replay_never_claims_live(self):
        for kind in ("IMAGE_FILE", "GIF_REPLAY", "VIDEO_REPLAY", "K230_JSONL"):
            with self.subTest(kind=kind):
                obs = valid_observation()
                obs["source"]["kind"] = kind
                self.assertIn("LIVE_SOURCE_NOT_VERIFIED", build_project_proposal(obs, 9)["blocking_reasons"])

    def test_clock_and_mount_must_be_explicitly_verified(self):
        for group, key in (("source", "capture_time_verified"), ("geometry", "mounting_verified"),
                           ("geometry", "metric_geometry_verified"), ("geometry", "direction_calibrated")):
            with self.subTest(group=group, key=key):
                obs = valid_observation()
                obs[group][key] = False
                self.assertIsNone(build_project_proposal(obs, 9)["feedback_frame"])

    def test_nonfinite_and_inconsistent_geometry_blocked(self):
        for position, angle in (([2, 1, 0], -0.5), ([2, float("nan"), 0], 0.5),
                                ([0, 1, 0], 1.0), ([1, 0, 0], float("inf"))):
            with self.subTest(position=position, angle=angle):
                obs = valid_observation()
                obs["geometry"]["relative_position_body_m"] = position
                obs["geometry"]["azimuth_rad"] = angle
                self.assertIsNone(build_project_proposal(obs, 9)["feedback_frame"])

    def test_unconfirmed_range_not_replaced_by_unit_ray(self):
        obs = valid_observation()
        obs["geometry"]["relative_position_body_m"] = None
        obs["geometry"]["unit_ray_body"] = [1.0, 0.0, 0.0]
        result = build_project_proposal(obs, 9)
        self.assertIn("FRONT_METRIC_POSITION_REQUIRED", result["blocking_reasons"])
        self.assertIsNone(result["candidate_feedback_fields"]["objects"][0]["relative_position_body"])

    def test_missing_or_invalid_timestep_is_not_inferred(self):
        for target in (None, 0, -1, 1.5, True):
            with self.subTest(target=target):
                result = build_project_proposal(valid_observation(), target)
                self.assertIsNone(result["target_neural_timestep_id"])
                self.assertIsNone(result["feedback_frame"])

    def test_invalid_status_count_center(self):
        for changes in ({"status": "STALE"}, {"object_count": 2}, {"object_count": 0},
                        {"selected_center_xy": [400, 20]}, {"status": "NO_TARGET"}):
            obs = valid_observation()
            obs.update(changes)
            self.assertEqual(build_project_proposal(obs, 9)["status"], "BLOCKED")

    def test_does_not_modify_input(self):
        obs = valid_observation()
        original = deepcopy(obs)
        result = build_project_proposal(obs, 9)
        result["source_observation"]["source"]["kind"] = "MUTATED"
        result["feedback_frame"]["objects"][0]["relative_position_body"][0] = 99
        self.assertEqual(obs, original)


if __name__ == "__main__":
    unittest.main()
