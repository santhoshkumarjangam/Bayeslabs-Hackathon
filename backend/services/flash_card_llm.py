import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

def generate_flashcards(topic: str, content: list[str], questions: list[str]) -> str:
    """
    Generates flashcard-style key bullet points for a given sprint session
    using the Gemini model via the google.genai package.
    
    Args:
        topic (str): The specific topic of the sprint (e.g., "Mitochondria").
        content (list[str]): Bullet points framing the study content.
        questions (list[str]): Questions framing the active recall portion.
        
    Returns:
        str: A formatted string containing key bullet points for active recall.
    """
    # Initialize the client. It automatically picks up GEMINI_API_KEY from the environment
    # if it's set. Alternatively, we can pass it explicitly.
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY not set in environment variables.")

    client = genai.Client(api_key=api_key)
    
    prompt = f"""
    ROLE: You are an elite Pedagogical AI Agent ("Micro-Session Orchestrator") specializing in high-yield, cognitive-science-backed study materials designed for rapid assimilation and final-hour exam preparation.

    OBJECTIVE: Distill the provided sprint context (Topic, Content, and Questions) into a series of professional, rigorous, and highly effective flashcard-style bullet points. Your goal is to maximize the student's short-term retention and active recall.

    OUTPUT SPECIFICATIONS:
    1. Target Audience: University-level or advanced students under strict time constraints.
    2. Format: Provide a carefully structured list of 5 to 10 distinct flashcard items.
    3. Content Focus: 
    - Core definitions and exact terminology derived from the content.
    - Crucial formulas, theorems, principles, or rule sets.
    - High-yield differentiators and answers to the provided active recall questions.
    - Formatted as active recall pairs when applicable (e.g., "Q: [Question] | A: [Answer]")
    4. Tone: Professional, authoritative, concise, and strictly academic.
    5. Constraints: Output ONLY the flashcard bullet points. Absolutely no introductory pleasantries, concluding remarks, meta-commentary, or markdown outside of the list itself.

    INPUT DATA:
    ---
    Topic: {topic}
    
    Content Highlights:
    {" | ".join(content) if content else "None provided."}
    
    Target Questions to Address:
    {" | ".join(questions) if questions else "None provided."}
    ---
    """

    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
    )
    
    return response.text.strip() if response.text else ""

# if __name__ == "__main__":
#     # A simple test to verify functionality
#     sample_topic = "Mitochondria and ATP Production"
#     sample_content = [
#         "Mitochondria are membrane-bound cell organelles that generate chemical energy.",
#         "Energy is stored in a small molecule called adenosine triphosphate (ATP)."
#     ]
#     sample_questions = [
#         "What is the primary morphological feature of mitochondria?",
#         "How is the chemical energy produced stored?"
#     ]
#     try:
#         print("Generated Flashcards:\n")
#         print(generate_flashcards(sample_topic, sample_content, sample_questions))
#     except Exception as e:
#         print(f"Error generating flashcards: {e}")
