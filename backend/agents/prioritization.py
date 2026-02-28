"""
PrioritizationAgent — High-yield topic sorter.
Takes extracted topics + time available and ranks what to study first.
"""
from __future__ import annotations
import json
import re
from typing import Any, List

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

from agents.schemas import PanicState, PrioritizedTopic

load_dotenv()


_INSTRUCTION = """
You are a high-stakes exam strategist. A panicking student has limited time.
Your job: rank the provided academic topics by how much studying each one is worth given the time constraint.

Rules:
- If time < 4 hours: ONLY "High Yield" + "Quick Win" topics. No deep dives.
- If time 4-12 hours: Include "Foundational" topics after high-yield ones.
- If time > 12 hours: Full balanced plan possible.

For each topic assign:
- priority: 1-10 (10 = study this first, matters most)
- estimated_time_mins: realistic study time in minutes
- yield_type: one of "High Yield", "Foundational", "Quick Win"

Return ONLY valid JSON — no markdown, no code fences:
[
  {
    "topic": "<topic name>",
    "priority": <1-10>,
    "estimated_time_mins": <integer>,
    "yield_type": "<High Yield|Foundational|Quick Win>"
  },
  ...
]
"""


class PrioritizationAgent:
    def __init__(self):
        self.agent = Agent(
            name="Prioritizer",
            model="gemini-2.5-flash",
            description="Ranks academic topics by exam yield given available time.",
            instruction=_INSTRUCTION,
        )
        self.runner = InMemoryRunner(
            agent=self.agent,
            app_name="cramming_crisis_coordinator",
        )

    async def prioritize(
        self, panic_state: PanicState, syllabus_text: str = ""
    ) -> List[PrioritizedTopic]:
        """Rank topics from a PanicState object, optionally using a syllabus for complete coverage."""
        topics_str = ", ".join(panic_state.topics_mentioned) if panic_state.topics_mentioned else "general exam topics"
        user_message = (
            f"Topics to study: {topics_str}\n"
            f"Time available: {panic_state.time_available_hours} hours\n"
            f"Student summary: {panic_state.summary}\n"
            f"Panic level: {panic_state.panic_level}/10\n"
        )
        if syllabus_text:
            user_message += (
                f"\nSyllabus / Course Outline (ALL topics that may appear on the exam):\n"
                f"{syllabus_text[:3000]}\n\n"
                "IMPORTANT: ensure every topic on the syllabus is included in the prioritized list, "
                "even if not mentioned above. Rank syllabus topics that overlap with weak topics highest.\n"
            )
        user_message += "\nPlease rank these topics and return the prioritized list as JSON."

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

        return _parse_topics(response_text, panic_state.topics_mentioned)


def _parse_topics(raw: str, fallback_topics: List[str]) -> List[PrioritizedTopic]:
    """Parse JSON list of prioritized topics from LLM response."""
    try:
        clean = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        data: list[dict[str, Any]] = json.loads(clean)
        return [
            PrioritizedTopic(
                topic=item.get("topic", "Unknown"),
                priority=int(item.get("priority", 5)),
                estimated_time_mins=int(item.get("estimated_time_mins", 15)),
                yield_type=item.get("yield_type", "High Yield"),
            )
            for item in data
        ]
    except Exception:
        # Graceful fallback
        return [
            PrioritizedTopic(
                topic=t,
                priority=max(1, 10 - i),
                estimated_time_mins=15,
                yield_type="High Yield",
            )
            for i, t in enumerate(fallback_topics or ["Core Concepts"])
        ]
