"""
ClarifyAgent — Adaptive "I still don't get X" responder.
When a student says they're stuck on a topic mid-session,
this agent breaks it down into a mini sub-sprint immediately.
"""
from __future__ import annotations
import json
import re
from typing import Any, List

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

from agents.schemas import SprintSession

load_dotenv()


_INSTRUCTION = """
You are a laser-focused exam tutor. A stressed student just said they STILL don't understand a specific topic even after studying it.

Your job: Break the topic into the smallest digestible sub-concepts and generate 1–3 ultra-short micro-sprints (5–10 minutes each) that specifically address the confusion.

Focus on:
- Using analogies and simple language
- Concrete examples over theory
- Active recall questions that test the exact point of confusion

Return ONLY valid JSON — no markdown, no code fences:
[
  {
    "sprint_number": <1, 2, ...>,
    "topic": "<sub-topic or specific aspect that's confusing>",
    "duration_mins": <5 or 10>,
    "activity_type": "<Active Recall|Flashcards|Blurting|Practice Problems>",
    "questions": ["<targeted question 1>", "<targeted question 2>"],
    "tips": "<simple analogy or memory trick for this exact confusion>"
  }
]
"""


class ClarifyAgent:
    def __init__(self):
        self.agent = Agent(
            name="ClarifyAgent",
            model="gemini-2.5-flash",
            description="Breaks down confusing topics into targeted micro-sprints when student says 'I still don't get X'.",
            instruction=_INSTRUCTION,
        )
        self.runner = InMemoryRunner(
            agent=self.agent,
            app_name="cramming_crisis_coordinator",
        )

    async def clarify_topic(
        self,
        confused_topic: str,
        student_context: str = "",
    ) -> List[SprintSession]:
        """Generate targeted sub-sprints for a topic the student is stuck on."""
        user_message = (
            f"The student says: 'I still don't get {confused_topic}'\n"
        )
        if student_context:
            user_message += f"Additional context: {student_context}\n"
        user_message += "\nBreak this down into targeted micro-sprints."

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

        return _parse_clarify_sprints(response_text, confused_topic)


def _parse_clarify_sprints(raw: str, topic: str) -> List[SprintSession]:
    """Parse clarification sprints from LLM response."""
    try:
        clean = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        data: list[dict[str, Any]] = json.loads(clean)
        return [
            SprintSession(
                sprint_number=int(item.get("sprint_number", i + 1)),
                topic=item.get("topic", topic),
                duration_mins=int(item.get("duration_mins", 7)),
                activity_type=item.get("activity_type", "Active Recall"),
                questions=item.get("questions", [f"Explain {topic} in simple terms."]),
                tips=item.get("tips"),
            )
            for i, item in enumerate(data)
        ]
    except Exception:
        return [
            SprintSession(
                sprint_number=1,
                topic=f"{topic} — Breakdown",
                duration_mins=10,
                activity_type="Active Recall",
                questions=[
                    f"In your own words, what is {topic}?",
                    f"Can you give a real-world example of {topic}?",
                    f"What part of {topic} specifically is confusing you?",
                ],
                tips=f"Try to explain {topic} out loud as if you're teaching it to someone else.",
            )
        ]
