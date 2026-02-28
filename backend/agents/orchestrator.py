"""
OrchestratorAgent — Sprint planner.
Takes prioritized topics and generates micro-sprint study sessions with active-recall questions.
"""
from __future__ import annotations
import json
import re
from typing import Any, List

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

from agents.schemas import PrioritizedTopic, SprintSession

load_dotenv()


_INSTRUCTION = """
You are a tactical exam-prep coach. You receive a ranked list of topics and turn them into
focused micro-sprint study sessions.

Sprint rules:
- Each sprint: 5–20 minutes
- Activity types: "Active Recall", "Flashcards", "Blurting", "Practice Problems"
- Include 3-5 active-recall questions per sprint — real exam-style questions, not vague ones.
- Higher priority topics get more sprints and more time.
- Add a "tips" field with one quick memory trick or shortcut.

Return ONLY valid JSON — no markdown, no code fences:
[
  {
    "sprint_number": <1, 2, 3, ...>,
    "topic": "<topic name>",
    "duration_mins": <integer>,
    "activity_type": "<Active Recall|Flashcards|Blurting|Practice Problems>",
    "questions": ["<Q1>", "<Q2>", "<Q3>"],
    "tips": "<one memory trick or exam tip>"
  },
  ...
]
"""


class OrchestratorAgent:
    def __init__(self):
        self.agent = Agent(
            name="Orchestrator",
            model="gemini-2.5-flash",
            description="Generates micro-sprint study sessions from prioritized topics.",
            instruction=_INSTRUCTION,
        )
        self.runner = InMemoryRunner(
            agent=self.agent,
            app_name="cramming_crisis_coordinator",
        )

    async def create_sprint_plan(
        self, topics: List[PrioritizedTopic], time_available_hours: float = 4.0
    ) -> List[SprintSession]:
        """Generate a list of SprintSession objects from prioritized topics."""
        topics_json = json.dumps(
            [t.model_dump() for t in topics], indent=2
        )
        user_message = (
            f"Total time available: {time_available_hours} hours "
            f"({int(time_available_hours * 60)} minutes)\n\n"
            f"Prioritized topics:\n{topics_json}\n\n"
            "Generate the sprint plan as JSON."
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

        return _parse_sprints(response_text, topics)


def _parse_sprints(raw: str, topics: List[PrioritizedTopic]) -> List[SprintSession]:
    """Parse JSON array of sprint sessions from LLM response."""
    try:
        clean = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        data: list[dict[str, Any]] = json.loads(clean)
        return [
            SprintSession(
                sprint_number=int(item.get("sprint_number", i + 1)),
                topic=item.get("topic", "Core Concepts"),
                duration_mins=int(item.get("duration_mins", 15)),
                activity_type=item.get("activity_type", "Active Recall"),
                questions=item.get("questions", ["What is the key concept here?"]),
                tips=item.get("tips"),
            )
            for i, item in enumerate(data)
        ]
    except Exception:
        # Graceful fallback: one sprint per topic
        return [
            SprintSession(
                sprint_number=i + 1,
                topic=t.topic,
                duration_mins=t.estimated_time_mins,
                activity_type="Active Recall",
                questions=[
                    f"What is the core idea behind {t.topic}?",
                    f"How would you explain {t.topic} to someone quickly?",
                    f"What is the most likely exam question about {t.topic}?",
                ],
                tips=None,
            )
            for i, t in enumerate(topics)
        ]
