import os
import google.genai as genai
from dotenv import load_dotenv
load_dotenv()


# Load Gemini API key from environment variable
GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GOOGLE_API_KEY not set in environment variables.")

genai.Client(api_key=GEMINI_API_KEY)

def generate_flashcards(topic_summary: str) -> str:
    """
    Given a topic summary, generate flash card style bullet points using Gemini LLM.
    Returns a string with key points for easy review.
    """
    prompt = f"""
    You are an expert at creating study flashcards. Given the following topic summary, generate concise, high-yield, flash card style bullet points. Focus on active recall, definitions, formulas, and key facts. Avoid long paragraphs. Format as a list of 5-10 bullet points. Do not include any extra commentary or instructions.

    Topic Summary:
    {topic_summary}
    """
    model = genai.Client(model= "gemini-2.0-flash")
    response = model.generate_content(prompt)
    return response.text.strip()
