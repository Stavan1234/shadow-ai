import re

# Deterministic Regex Rules
DOCUMENT = re.compile(r"\.(pdf|docx|txt|md)\b|\b(pdf|document|docx|text file|md)\b|\bthis (document|file|pdf)\b|\b(the|in) (pdf|document)\b|\bin (the )?file\b", re.I)
DEEP = re.compile(r"\b(figure out|debug|compare|why (is|does)|analyze|reason)\b", re.I)
MEMORY = re.compile(r"\b(remember|recall|what did i|last time|earlier|my project|previously|history|memory|stored)\b", re.I)
ACTION = re.compile(r"\b(create|delete|write|open|move|rename|list|find|run|make|execute|mkdir)\b", re.I)
DESTRUCTIVE_ACTION = re.compile(r"\b(create|delete|remove|write|move|rename|mkdir)\b", re.I)
GREETING = re.compile(r"^\s*(hi|hey|hello|thanks|thank you|good (morning|night|afternoon|evening))\b", re.I)

def route(text: str) -> str:
    """
    Deterministic regex-based router.
    Routes text into one of the 5 conversational tiers.
    """
    cleaned = text.strip()
    
    # 1. Tier 4: Deep Reasoning / Agent Reasoning
    if DEEP.search(cleaned):
        return "TIER_4_DEEP_REASONING"
        
    # 2. Tier 2: Subconscious Memory / Direct LanceDB Recall
    if MEMORY.search(cleaned):
        return "TIER_2_MEMORY"
        
    # 3. Tier 3: Action (Explicit destructive file system manipulation)
    # If the user explicitly asks to create, delete, write, move, or rename a file/folder,
    # it must be classified as Tier 3 Action, even if it mentions a document or file extension.
    if DESTRUCTIVE_ACTION.search(cleaned):
        return "TIER_3_ACTION"
        
    # 4. Tier 5: Document Q&A (Matches reading/interpreting documents)
    if DOCUMENT.search(cleaned):
        return "TIER_5_DOCUMENT_QA"
        
    # 5. Tier 3: Action (Non-destructive actions like list, run, find file, open folder)
    if ACTION.search(cleaned):
        return "TIER_3_ACTION"
        
    # 6. Tier 1: Foreground Chat / Greetings (Default Fallback)
    if GREETING.match(cleaned):
        return "TIER_1_CHAT"
        
    return "TIER_1_CHAT"
