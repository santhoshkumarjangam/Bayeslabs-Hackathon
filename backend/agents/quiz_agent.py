"""
QuizAgent — Diagnostic knowledge checker.
Generates multiple-choice questions from extracted notes/syllabus to assess
the student's baseline knowledge per topic before building their study plan.
"""
from __future__ import annotations
import json
import re
import uuid
from typing import Any, List

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

from agents.schemas import PanicState, QuizQuestion

load_dotenv()


_INSTRUCTION = """
You are an expert exam question writer. A student has uploaded their notes or syllabus.
Your job is to generate a diagnostic quiz of multiple-choice questions (MCQs) to assess 
their baseline knowledge on the identified topics.

Rules:
- Generate exactly the number of questions requested (spread across the identified topics).
- Each question must have exactly 4 answer choices: A, B, C, D.
- Vary difficulty: mix of easy (recall), medium (application), and hard (analysis).
- The correct answer must be unambiguously correct.
- Questions should reflect what would actually appear on the exam.

Return ONLY valid JSON — no markdown, no code fences:
[
  {
    "topic": "<topic this question tests>",
    "question": "<the question text>",
    "choices": ["A) <choice>", "B) <choice>", "C) <choice>", "D) <choice>"],
    "correct_answer": "<A|B|C|D>",
    "difficulty": "<easy|medium|hard>"
  },
  ...
]
"""


class QuizAgent:
    def __init__(self):
        self.agent = Agent(
            name="QuizAgent",
            model="gemini-2.5-flash",
            description="Generates diagnostic MCQ questions from student notes to identify weak spots.",
            instruction=_INSTRUCTION,
        )
        self.runner = InMemoryRunner(
            agent=self.agent,
            app_name="cramming_crisis_coordinator",
        )

    async def generate_quiz(
        self,
        panic_state: PanicState,
        notes_text: str,
        num_questions: int = 10,
    ) -> List[QuizQuestion]:
        """Generate MCQ diagnostic questions from the student's notes."""
        topics = panic_state.topics_mentioned
        topics_str = ", ".join(topics) if topics else "the main exam topics"

        # Truncate notes to avoid token limits — first 3000 chars is enough context
        notes_preview = notes_text[:3000] if len(notes_text) > 3000 else notes_text

        user_message = (
            f"Student's exam topics: {topics_str}\n"
            f"Time available: {panic_state.time_available_hours} hours\n\n"
            f"--- Notes Preview ---\n{notes_preview}\n---\n\n"
            f"Generate exactly {num_questions} diagnostic MCQ questions "
            f"spread across: {topics_str}. "
            f"Focus on what's most likely to appear in an exam on these topics."
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

        return _parse_questions(response_text, topics)


def _parse_questions(raw: str, topics: List[str]) -> List[QuizQuestion]:
    """Parse MCQ list from LLM response."""
    try:
        clean = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        data: list[dict[str, Any]] = json.loads(clean)
        questions = []
        for i, item in enumerate(data):
            questions.append(
                QuizQuestion(
                    id=f"q{i + 1}",
                    topic=item.get("topic", topics[i % len(topics)] if topics else "General"),
                    question=item.get("question", ""),
                    choices=item.get("choices", ["A) ?", "B) ?", "C) ?", "D) ?"]),
                    correct_answer=item.get("correct_answer", "A").upper().strip(),
                    difficulty=item.get("difficulty", "medium"),
                )
            )
        return questions
    except Exception:
        # Fallback: basic questions for each topic
        fallback = []
        for i, topic in enumerate(topics[:5] or ["Core Concepts"]):
            fallback.append(
                QuizQuestion(
                    id=f"q{i + 1}",
                    topic=topic,
                    question=f"Which statement best describes {topic}?",
                    choices=[
                        f"A) Core definition of {topic}",
                        f"B) An unrelated concept",
                        f"C) A common misconception about {topic}",
                        f"D) None of the above",
                    ],
                    correct_answer="A",
                    difficulty="easy",
                )
            )
        return fallback
