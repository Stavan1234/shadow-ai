import os
import json
import unittest
from pathlib import Path
import sys

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.state.machine import ShadowState, set_state
from src.orchestrator import check_sleep_command
from src.tts.speak import pre_render_fillers, FILLERS

class TestVoiceIO(unittest.TestCase):
    def setUp(self):
        self.status_file = PROJECT_ROOT / "data" / "status.json"
        self.filler_dir = PROJECT_ROOT / "data" / "fillers"

    def test_state_machine_writes_status(self):
        """Test that state machine correctly transitions and writes status.json."""
        set_state(ShadowState.LISTENING)
        self.assertTrue(self.status_file.exists())
        
        with open(self.status_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.assertEqual(data.get("state"), "LISTENING")
            
        set_state(ShadowState.ASLEEP)
        with open(self.status_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.assertEqual(data.get("state"), "ASLEEP")

    def test_sleep_command_detection(self):
        """Test that sleep phrases are detected accurately and other text is ignored."""
        self.assertTrue(check_sleep_command("go to sleep shadow"))
        self.assertTrue(check_sleep_command("shadow go to sleep"))
        self.assertTrue(check_sleep_command("shadow sleep now"))
        self.assertTrue(check_sleep_command("  Go To Sleep Shadow  "))
        
        self.assertFalse(check_sleep_command("sleep"))
        self.assertFalse(check_sleep_command("shadow"))
        self.assertFalse(check_sleep_command("please go to sleep"))
        self.assertFalse(check_sleep_command("hello shadow"))

    def test_filler_rendering(self):
        """Test that filler phrases can be pre-rendered and saved to the data folder."""
        # Run pre-rendering to check behavior
        pre_render_fillers()
        
        from src.tts.speak import PIPER_MODEL
        model_name = PIPER_MODEL.stem
        
        self.assertTrue(self.filler_dir.exists())
        for i in range(len(FILLERS)):
            out_file = self.filler_dir / f"filler_{model_name}_{i}.wav"
            self.assertTrue(out_file.exists(), f"Filler file {out_file.name} was not generated.")
            self.assertGreater(out_file.stat().st_size, 1024, f"Filler file {out_file.name} is too small.")

if __name__ == "__main__":
    unittest.main()
