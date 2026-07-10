import os
import sys
import unittest
import asyncio
from pathlib import Path

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.memory.fast_recall import fast_recall
from src.memory.document_qa import extract_text, answer_from_document, queue_document_fact
from src.memory.cognee_worker import memory_queue, memory_worker

class TestMemorySystems(unittest.TestCase):
    def setUp(self):
        # Create a dummy text file for Document QA testing
        self.dummy_file = PROJECT_ROOT / "data" / "test_dummy.txt"
        os.makedirs(self.dummy_file.parent, exist_ok=True)
        with open(self.dummy_file, "w", encoding="utf-8") as f:
            f.write("S.H.A.D.O.W. stands for Synthetic Humanoid Agent for Desktop Operations and Workflows.")

    def tearDown(self):
        # Clean up dummy file
        if self.dummy_file.exists():
            try:
                os.remove(self.dummy_file)
            except Exception:
                pass

    def test_extract_text_txt(self):
        """Test extraction of plain text file."""
        content = extract_text(str(self.dummy_file))
        self.assertIn("Synthetic Humanoid Agent", content)

    def test_extract_text_nonexistent(self):
        """Test extraction of nonexistent file returns empty string."""
        content = extract_text("nonexistent_file.pdf")
        self.assertEqual(content, "")

    def test_fast_recall_execution(self):
        """Test that fast_recall queries LanceDB without raising errors."""
        # It should run fine even if no records are found (returns list)
        results = fast_recall("test query")
        self.assertIsInstance(results, list)

    def test_enqueue_memory_fact(self):
        """Test that facts can be successfully enqueued to the memory worker queue."""
        async def run_queue_test():
            # Clear queue first
            while not memory_queue.empty():
                memory_queue.get_nowait()
                
            await memory_queue.put("Test fact 1")
            self.assertEqual(memory_queue.qsize(), 1)
            
            fact = await memory_queue.get()
            self.assertEqual(fact, "Test fact 1")
            memory_queue.task_done()
            
        asyncio.run(run_queue_test())

if __name__ == "__main__":
    unittest.main()
