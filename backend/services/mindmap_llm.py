import os
import json
from google import genai
from dotenv import load_dotenv

load_dotenv()

def generate_mindmap(document_text: str) -> str:
    """
    Generates a solid, creative, and interactive mindmap representation (Mermaid.js format)
    by analyzing the raw text of a study document.
    
    Args:
        document_text (str): The raw text extracted from a study document (e.g., from PDF or notes).
        
    Returns:
        str: A Markdown string containing a Mermaid.js diagram code block.
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY not set in environment variables.")

    client = genai.Client(api_key=api_key)
    
    prompt = f"""
    ROLE: You are an elite Pedagogical AI Agent ("Visual Knowledge Architect") specializing in cognitive mapping and accelerated learning for last-minute exam preparation.

    OBJECTIVE: Read the provided `Raw Document Text` and autonomously deduce its overarching subject, major modules/themes, and underlying topics. Transform this deduced structure into a highly visual, structured, and easy-to-understand Mermaid.js diagram. The output should serve as an interactive "mind map" that helps students quickly grasp the overall structure of the document.

    DESIGN RULES & CONSTRAINTS:
    1. Format: Output valid `mermaid` code enclosed in markdown blocks (```mermaid ... ```).
    2. Diagram Type: Use `mindmap` or `graph LR` (Left to Right flowchart) in Mermaid.js to represent the hierarchy.
    3. Color Coding (CRITICAL): You must logically evaluate each module's typical difficulty for a student.
    - Hard/Complex modules MUST be styled with a RED background.
    - Medium difficulty modules MUST be styled with a YELLOW background.
    - Easy/Foundational modules MUST be styled with a GREEN background.
    4. Structure:
    - Central Node = The inferred overarching Subject or Title of the document.
    - Level 1 Nodes = Major modules/sections (Apply the color coding here).
    - Level 2 Nodes = Key topics under each module.
    5. Tone: Analytical, structured, and visually clean. Do NOT include extraneous text outside the mermaid block.
    6. The colors serve as a triage signal for the "Micro-Session Orchestrator" to prioritize the student's final hours.

    INPUT DATA:
    ---
    Raw Document Text:
    {document_text}
    ---
    """

    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
    )
    
    return response.text.strip() if response.text else ""

# if __name__ == "__main__":
#     # Test execution
#     subject_name = "Introduction to Computer Science"
#     sample_curriculum = {
#         "Variables & Data Types": ["Integers", "Strings", "Booleans"],
#         "Control Structures": ["If-Else Statements", "For Loops", "While Loops"],
#         "Algorithms & Data Structures": ["Recursion", "Dynamic Programming", "Trees & Graphs"],
#         "Basic Syntax": ["Print Statements", "Comments"]
#     }
    
#     try:
#         print("Generating Mindmap...\n")
#         print(generate_mindmap(subject_name, sample_curriculum))
#     except Exception as e:
#         print(f"Error generating mindmap: {e}")
