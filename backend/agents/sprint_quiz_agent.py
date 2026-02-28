"""
SprintQuizAgent — Generates topic-wise MCQs for a completed sprint.
Questions are based on the sprint's topic, study content bullets, and difficulty level.
Each question includes a detailed explanation of the correct answer (for post-submission display).
"""
from __future__ import annotations
import json
import re
from typing import Any, List

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

load_dotenv()


_INSTRUCTION = """
You are a precise exam question generator. Given a topic, its study content bullets, and
difficulty level, generate multiple-choice quiz questions to test understanding of that sprint.

Rules:
- Each question must have exactly 4 choices: A), B), C), D)
- The correct_answer must be exactly one of: "A", "B", "C", "D"
- Questions must be directly based on the provided content — not generic
- Vary difficulty: some recall-based, some application-based
- IMPORTANT: Write a clear "explanation" (2-3 sentences) explaining WHY the correct answer
  is right and why the others are wrong. This is shown AFTER the student submits.

Return ONLY valid JSON — no markdown, no code fences:
[
  {
    "question_id": "sq1",
    "question": "<specific question about the content>",
    "choices": ["A) ...", "B) ...", "C) ...", "D) ..."],
    "correct_answer": "A",
    "explanation": "<Why A is correct. Why B, C, D are wrong.>",
    "difficulty": "easy|medium|hard"
  },
  ...
]
"""


class SprintQuizAgent:
    def __init__(self):
        self.agent = Agent(
            name="SprintQuizAgent",
            model="gemini-2.5-flash",
            description="Generates topic-wise MCQs for a completed sprint.",
            instruction=_INSTRUCTION,
        )
        self.runner = InMemoryRunner(
            agent=self.agent,
            app_name="cramming_crisis_coordinator",
        )

    async def generate_sprint_quiz(
        self,
        topic: str,
        content: List[str],
        num_questions: int = 5,
    ) -> list[dict]:
        """
        Generate MCQs for a sprint topic.
        Returns a list of raw dicts (not yet persisted) with question, choices,
        correct_answer, and explanation.
        """
        content_text = "\n".join(content) if content else f"Core concepts of {topic}"
        user_message = (
            f"Topic: {topic}\n\n"
            f"Study Content:\n{content_text}\n\n"
            f"Generate exactly {num_questions} quiz questions based on the content above. "
            "Make them specific to the bullet points — not general questions."
        )

        session = await self.runner.session_service.create_session(
            app_name="cramming_crisis_coordinator",
            user_id="student",
        )

        response_text = ""
        async for event in self.runner.run_async(
            user_id="student",
            session_id=session.id,
            new_message=genai_types.Content(
                role="user",
                parts=[genai_types.Part(text=user_message)],
            ),
        ):
            if event.is_final_response() and event.content and event.content.parts:
                response_text = event.content.parts[0].text
                break

        return _parse_questions(response_text, topic, num_questions)


def _parse_questions(raw: str, topic: str, num_questions: int) -> list[dict]:
    """Parse JSON from LLM and return list of question dicts."""
    try:
        clean = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        data: list[dict[str, Any]] = json.loads(clean)
        # Validate + normalise
        questions = []
        for i, item in enumerate(data):
            questions.append({
                "question_id": item.get("question_id", f"sq{i + 1}"),
                "question": item.get("question", f"What is a key concept of {topic}?"),
                "choices": item.get("choices", ["A) Option A", "B) Option B", "C) Option C", "D) Option D"]),
                "correct_answer": item.get("correct_answer", "A").upper().strip(),
                "explanation": item.get("explanation", "The correct answer is the most accurate based on the content."),
                "difficulty": item.get("difficulty", "medium"),
            })
        return questions
    except Exception:
        # Fallback: generic questions
        return [
            {
                "question_id": f"sq{i + 1}",
                "question": f"What is concept #{i + 1} about {topic}?",
                "choices": ["A) Definition", "B) Application", "C) Example", "D) Formula"],
                "correct_answer": "A",
                "explanation": f"This tests understanding of {topic} fundamentals.",
                "difficulty": "medium",
            }
            for i in range(num_questions)
        ]
