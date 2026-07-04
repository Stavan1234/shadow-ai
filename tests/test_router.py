import unittest
from pathlib import Path
import sys

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.router.tiers import route

class TestRouter(unittest.TestCase):
    def setUp(self):
        # 15 phrases for TIER_1_CHAT
        self.tier_1_phrases = [
            "Hi",
            "Hello there",
            "Hey Shadow",
            "Thanks",
            "Thank you very much",
            "Good morning",
            "Good night, sleep well",
            "How is the weather today?",
            "Tell me a joke",
            "Who are you?",
            "Can you help me?",
            "What's up?",
            "Okay, interesting",
            "Yes, please",
            "No thank you"
        ]

        # 15 phrases for TIER_2_MEMORY
        self.tier_2_phrases = [
            "Remember my keys are on the table",
            "Recall what we did yesterday",
            "What did I say about my project?",
            "Do you remember the meeting time?",
            "What did we talk about earlier?",
            "Do you recall my friend's name?",
            "Check my project details",
            "Show previously stored facts",
            "Look at conversational history",
            "Tell me what did I tell you last time",
            "What did I do earlier today?",
            "Recall the previous notes",
            "Remember to buy milk",
            "What did I write in my project folder?",
            "Retrieve memory details"
        ]

        # 15 phrases for TIER_3_ACTION
        self.tier_3_phrases = [
            "Create a folder named src",
            "Delete the temp directory",
            "Write this code to main.py",
            "Open my Desktop folder",
            "Move index.html to build/",
            "Rename doc.txt to report.txt",
            "List all files in the directory",
            "Find the file named config.json",
            "Run the build task",
            "Execute run_shadow.py",
            "Make a directory here",
            "mkdir test_folder",
            "Run python script",
            "Create file log.txt",
            "Delete main.py"
        ]

        # 15 phrases for TIER_4_DEEP_REASONING
        self.tier_4_phrases = [
            "Figure out why my server is crashing",
            "Debug this stack trace",
            "Compare these two databases",
            "Why is my compiler throwing this error?",
            "Why does this function return None?",
            "Analyze this log file",
            "Reason about this algorithm",
            "Figure out how to optimize this loop",
            "Compare performance of LanceDB vs PostgreSQL",
            "Why is the memory usage growing?",
            "Debug the threading deadlock",
            "Analyze the complexity of this sort function",
            "Compare Qwen 3B vs 7B",
            "Figure out the root cause",
            "Why does it trigger on VAD?"
        ]

        # 15 phrases for TIER_5_DOCUMENT_QA
        self.tier_5_phrases = [
            "Read this document.pdf",
            "Summarize report.docx",
            "Look inside info.txt",
            "Open the read_me.md file",
            "What is in this document?",
            "Answer questions based on the pdf",
            "What does this file say?",
            "Look up in the document",
            "Find information in the pdf file",
            "Read instructions in the md file",
            "What did this document conclude?",
            "Check details in the file",
            "Read the pdf about space",
            "Open this document",
            "Summarize this pdf file"
        ]

    def test_tier_1_chat(self):
        for phrase in self.tier_1_phrases:
            tier = route(phrase)
            self.assertEqual(tier, "TIER_1_CHAT", f"Failed for phrase: '{phrase}', classified as {tier}")

    def test_tier_2_memory(self):
        for phrase in self.tier_2_phrases:
            tier = route(phrase)
            self.assertEqual(tier, "TIER_2_MEMORY", f"Failed for phrase: '{phrase}', classified as {tier}")

    def test_tier_3_action(self):
        for phrase in self.tier_3_phrases:
            tier = route(phrase)
            self.assertEqual(tier, "TIER_3_ACTION", f"Failed for phrase: '{phrase}', classified as {tier}")

    def test_tier_4_deep_reasoning(self):
        for phrase in self.tier_4_phrases:
            tier = route(phrase)
            self.assertEqual(tier, "TIER_4_DEEP_REASONING", f"Failed for phrase: '{phrase}', classified as {tier}")

    def test_tier_5_document_qa(self):
        for phrase in self.tier_5_phrases:
            tier = route(phrase)
            self.assertEqual(tier, "TIER_5_DOCUMENT_QA", f"Failed for phrase: '{phrase}', classified as {tier}")

if __name__ == "__main__":
    unittest.main()
