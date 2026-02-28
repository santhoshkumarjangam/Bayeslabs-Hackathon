"""
PanicIntakeAgent — First responder.
Calms the student, extracts topics and panic level from free-form text.
"""
from __future__ import annotations
import json
import os
import re
from typing import Any

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

from agents.schemas import PanicState

load_dotenv()


_INSTRUCTION = """
You are the first point of contact for a stressed student who is about to panic.

Your job:
1. Remain calm and supportive.
2. Read the student's message carefully.
3. Extract key study information.
4. Return ONLY valid JSON — no markdown, no code fences, just raw JSON.

Return this exact JSON structure:
{
  "panic_level": <integer 1-10, 10 = full meltdown>,
  "topics_mentioned": [<list of academic topics found in the text>],
  "time_available_hours": <float, hours until the exam — default 4 if not mentioned>,
  "urgency_reason": "<short phrase like 'Exam in 3 hours'>",
  "summary": "<one paragraph: what the student has vs what they need to learn>"
}
"""


class PanicIntakeAgent:
    def __init__(self):
        self.agent = Agent(
            name="PanicIntake",
            model="gemini-2.5-flash",
            description="Calms the student and extracts study context from their panicked message.",
            instruction=_INSTRUCTION,
        )
        self.runner = InMemoryRunner(
            agent=self.agent,
            app_name="cramming_crisis_coordinator",
        )

    async def parse_student_input(self, student_input: str) -> PanicState:
        """Run the intake agent and parse the extracted information."""
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
                parts=[genai_types.Part(text=student_input)],
            ),
        ):
            if event.is_final_response() and event.content and event.content.parts:
                response_text = event.content.parts[0].text
                break

        return _parse_panic_state(response_text, student_input)

    # Keep backward-compatible sync stub
    def process_input(self, student_input: str) -> PanicState:
        return PanicState(
            panic_level=8,
            extracted_text=student_input,
            topics_mentioned=[],
            urgency_reason="Exam soon",
            summary=student_input[:200],
        )


def _parse_panic_state(raw: str, original_input: str) -> PanicState:
    """Extract JSON from the LLM response robustly."""
    try:
        # Strip markdown code fences if present
        clean = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        data: dict[str, Any] = json.loads(clean)
        return PanicState(
            panic_level=int(data.get("panic_level", 7)),
            extracted_text=original_input,
            topics_mentioned=data.get("topics_mentioned", []),
            time_available_hours=float(data.get("time_available_hours", 4.0)),
            urgency_reason=data.get("urgency_reason"),
            summary=data.get("summary", ""),
        )
    except Exception:
        # Graceful fallback — still return something useful
        return PanicState(
            panic_level=7,
            extracted_text=original_input,
            topics_mentioned=[],
            time_available_hours=4.0,
            urgency_reason="Exam soon",
            summary=f"Student input: {original_input[:300]}",
        )
