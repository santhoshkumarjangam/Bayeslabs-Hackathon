import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

def generate_flashcards(topic_summary: str) -> str:
    """
    Generates flashcard-style key bullet points for a given topic summary 
    using the Gemini model via the google.genai package.
    
    Args:
        topic_summary (str): The text summary of the topic to create flashcards for.
        
    Returns:
        str: A formatted string containing key bullet points for active recall.
    """
    # Initialize the client. It automatically picks up GEMINI_API_KEY from the environment
    # if it's set. Alternatively, we can pass it explicitly.
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY not set in environment variables.")

    client = genai.Client(api_key=api_key)
    
    prompt = f"""
    ROLE: You are an elite Pedagogical AI Agent ("Micro-Session Orchestrator") specializing in high-yield, cognitive-science-backed study materials designed for rapid assimilation and final-hour exam preparation.

    OBJECTIVE: Distill the provided `Topic Summary` into a series of professional, rigorous, and highly effective flashcard-style bullet points. Your goal is to maximize the student's short-term retention and active recall.

    OUTPUT SPECIFICATIONS:
    1. Target Audience: University-level or advanced students under strict time constraints.
    2. Format: Provide a carefully structured list of 5 to 10 distinct flashcard items.
    3. Content Focus: 
    - Core definitions and exact terminology
    - Crucial formulas, theorems, principles, or rule sets
    - High-yield differentiators (e.g., key distinctions between similar concepts)
    - Formatted as active recall pairs when applicable (e.g., "Q: [Question] | A: [Answer]")
    4. Tone: Professional, authoritative, concise, and strictly academic.
    5. Constraints: Output ONLY the flashcard bullet points. Absolutely no introductory pleasantries, concluding remarks, meta-commentary, or markdown outside of the list itself.

    INPUT DATA:
    ---
    Topic Summary:
    {topic_summary}
    ---
    """



    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
    )
    
    return response.text.strip() if response.text else ""

if __name__ == "__main__":
    # A simple test to verify functionality
    sample_summary = (
        "Mitochondria are membrane-bound cell organelles (mitochondrion, singular) "
        "that generate most of the chemical energy needed to power the cell's "
        "biochemical reactions. Chemical energy produced by the mitochondria is "
        "stored in a small molecule called adenosine triphosphate (ATP)."
    )
    try:
        print("Generated Flashcards:\n")
        print(generate_flashcards(sample_summary))
    except Exception as e:
        print(f"Error generating flashcards: {e}")
