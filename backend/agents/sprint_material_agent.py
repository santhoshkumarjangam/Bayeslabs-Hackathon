"""
SprintMaterialAgent — Expands sprint bullet points into 1-2 pages of detailed
study material, grounding the explanation in the student's original notes and syllabus.
"""
from __future__ import annotations
from typing import Optional

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

load_dotenv()


_INSTRUCTION = """
You are an expert tutor creating detailed study material for a specific exam topic.
Your goal is to write 1-2 pages of comprehensive, easy-to-read study notes perfectly
aligned with the topic and sprint goals.

You will be given:
1. The sprint topic and the specific bullet points the sprint must cover.
2. The student's original uploaded notes and syllabus context.

Rules:
- Write in clear, well-structured Markdown (headers, bullet points, bold text).
- Length should be roughly 1 to 2 pages (500-1000 words).
- If formulas or code are relevant, format them in markdown blocks.
- Draw directly from the uploaded context if provided; if the context is thin,
  fill in the gaps using your own knowledge to ensure the topic is fully explained.
- Explain concepts simply, as the student is cramming. Use analogies where helpful.
- Provide examples for complex ideas.
- End with a brief "Key Takeaways" summary.

DO NOT output JSON. Return raw markdown text ready to be displayed to the user.
"""


class SprintMaterialAgent:
    def __init__(self):
        self.agent = Agent(
            name="SprintMaterialTutor",
            model="gemini-2.5-flash",
            description="Generates 1-2 pages of detailed study material for a sprint topic.",
            instruction=_INSTRUCTION,
        )
        self.runner = InMemoryRunner(
            agent=self.agent,
            app_name="cramming_crisis_coordinator",
        )

    async def generate_material(
        self,
        topic: str,
        content_bullets: list[str],
        notes_context: str,
        syllabus_context: str,
    ) -> str:
        """
        Generate comprehensive study notes for a sprint.
        """
        bullets_text = "\n".join(f"- {b}" for b in content_bullets)
        
        user_message = (
            f"# Target Topic: {topic}\n\n"
            f"## Specific Sprint Goals (Must Cover):\n{bullets_text}\n\n"
        )
        
        if syllabus_context:
             user_message += f"## Syllabus Context:\n{syllabus_context[:2000]}\n\n"
             
        if notes_context:
             user_message += f"## Student's Original Notes:\n{notes_context[:4000]}\n\n"

        user_message += "Please generate 1-2 pages of comprehensive, markdown-formatted study material covering this topic."

        session = await self.runner.session_service.create_session(
            app_name="cramming_crisis_coordinator",
            user_id="material_generator",
        )

        response_text = ""
        async for event in self.runner.run_async(
            user_id="material_generator",
            session_id=session.id,
            new_message=genai_types.Content(
                role="user",
                parts=[genai_types.Part(text=user_message)],
            ),
        ):
            if event.is_final_response() and event.content and event.content.parts:
                response_text = event.content.parts[0].text
                break

        return response_text.strip() or "Material generation failed. Please try again."
