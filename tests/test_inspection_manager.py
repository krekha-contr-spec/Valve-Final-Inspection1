import unittest
import os
import shutil
import numpy as np
from datetime import datetime

from storage_manager import storage_manager
from inspection_session import InspectionSessionManager, InspectionState, ACTIVE_SESSION_FILE


class TestInspectionManager(unittest.TestCase):

    def setUp(self):
        self.manager = InspectionSessionManager()
        # Ensure fresh state
        self.manager.reset_or_recover("discard")

    def tearDown(self):
        self.manager.reset_or_recover("discard")

    def create_dummy_frame(self, color_value: int = 128):
        frame = np.full((100, 100, 3), color_value, dtype=np.uint8)
        return frame

    def test_complete_when_all_required_captured(self):
        """Test 1: Required = 5, Captured = 5 -> COMPLETE"""
        session = self.manager.start_new_session(valve_type="Ball Valve")
        inspection_id = session["inspection_id"]
        positions = session["positions"]
        self.assertEqual(session["required_images"], 5)

        for i, pos in enumerate(positions):
            frame = self.create_dummy_frame(color_value=10 * (i + 1))
            success, msg, img_meta = self.manager.record_captured_image(
                inspection_id=inspection_id,
                camera_id="CAM-01",
                position=pos,
                frame=frame
            )
            self.assertTrue(success, f"Failed to record {pos}: {msg}")

        complete, msg = self.manager.is_inspection_complete(inspection_id)
        self.assertTrue(complete, f"Expected complete inspection: {msg}")

    def test_incomplete_when_missing_images(self):
        """Test 2: Required = 6, Captured = 5 -> INCOMPLETE"""
        session = self.manager.start_new_session(valve_type="Check Valve")
        inspection_id = session["inspection_id"]
        positions = session["positions"]
        self.assertEqual(session["required_images"], 6)

        # Capture only 5 of 6 required views
        for i in range(5):
            pos = positions[i]
            frame = self.create_dummy_frame(color_value=20 * (i + 1))
            success, msg, _ = self.manager.record_captured_image(
                inspection_id=inspection_id,
                camera_id="CAM-01",
                position=pos,
                frame=frame
            )
            self.assertTrue(success)

        complete, msg = self.manager.is_inspection_complete(inspection_id)
        self.assertFalse(complete)
        self.assertIn("Captured 5 of 6", msg)

    def test_ten_images_required_complete(self):
        """Test 3: Required = 10, Captured = 10 -> COMPLETE"""
        session = self.manager.start_new_session(valve_type="Globe Valve")
        inspection_id = session["inspection_id"]
        positions = session["positions"]
        self.assertEqual(session["required_images"], 10)

        for i, pos in enumerate(positions):
            frame = self.create_dummy_frame(color_value=5 * (i + 1))
            success, msg, _ = self.manager.record_captured_image(
                inspection_id=inspection_id,
                camera_id="CAM-01",
                position=pos,
                frame=frame
            )
            self.assertTrue(success)

        complete, msg = self.manager.is_inspection_complete(inspection_id)
        self.assertTrue(complete)

    def test_duplicate_image_rejection(self):
        """Test 4: Duplicate image capture must be detected and rejected."""
        session = self.manager.start_new_session(valve_type="Ball Valve")
        inspection_id = session["inspection_id"]
        pos = session["positions"][0]

        frame = self.create_dummy_frame(color_value=200)

        # First capture
        success1, msg1, _ = self.manager.record_captured_image(
            inspection_id=inspection_id,
            camera_id="CAM-01",
            position=pos,
            frame=frame
        )
        self.assertTrue(success1)

        # Duplicate capture with identical frame array
        success2, msg2, _ = self.manager.record_captured_image(
            inspection_id=inspection_id,
            camera_id="CAM-01",
            position=pos,
            frame=frame
        )
        self.assertFalse(success2)
        self.assertIn("Duplicate", msg2)

    def test_prevent_image_mixing(self):
        """Test 5: Capturing for an inactive inspection ID must fail."""
        session1 = self.manager.start_new_session(valve_type="Ball Valve")
        id1 = session1["inspection_id"]

        frame = self.create_dummy_frame(color_value=150)
        success, msg, _ = self.manager.record_captured_image(
            inspection_id="INS-WRONG-0000",
            camera_id="CAM-01",
            position="Front",
            frame=frame
        )
        self.assertFalse(success)
        self.assertIn("Inspection ID mismatch", msg)

    def test_incomplete_inspection_recovery(self):
        """Test 6: Active session saved to file can be recovered upon restart."""
        session = self.manager.start_new_session(valve_type="Ball Valve")
        id1 = session["inspection_id"]

        frame = self.create_dummy_frame(color_value=99)
        self.manager.record_captured_image(
            inspection_id=id1,
            camera_id="CAM-01",
            position="Front",
            frame=frame
        )

        # Simulate app restart by creating a new manager instance
        new_manager = InspectionSessionManager()
        recovered_status = new_manager.get_current_status()

        self.assertTrue(recovered_status["active"])
        self.assertEqual(recovered_status["inspection_id"], id1)
        self.assertEqual(recovered_status["captured_count"], 1)


if __name__ == "__main__":
    unittest.main()
