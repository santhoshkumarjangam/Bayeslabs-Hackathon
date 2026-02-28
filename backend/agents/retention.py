"""
RetentionBoosterAgent — Fatigue & retention monitor.
Watches the student's performance score and time-on-topic to recommend actions.
"""
from __future__ import annotations
import json
import re
from typing import Any

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

from agents.schemas import RetentionAdvice

load_dotenv()


_INSTRUCTION = """
You are a student wellbeing and retention coach during a high-pressure cramming session.

You receive real-time signals about the student's performance. Based on these signals,
recommend one of the following actions:
- "Keep Going" — student is doing well, stay the course
- "Review" — student should quickly review a previous topic (spaced repetition)
- "Switch Topic" — student has been stuck too long, move on
- "Break" — student is fatigued, needs a 5-minute mental reset
- "Sleep" — extremely fatigued, a 20-min nap would help more than studying

Return ONLY valid JSON — no markdown, no code fences:
{
  "action": "<Keep Going|Review|Switch Topic|Break|Sleep>",
  "message": "<supportive, specific 1-2 sentence message to the student>",
  "target_topic": "<only fill if action is Review, else null>",
  "suggested_duration_mins": <null or integer number of minutes for break/review>
}
"""


class RetentionBoosterAgent:
    def __init__(self):
        self.agent = Agent(
            name="RetentionBooster",
            model="gemini-2.5-flash",
            description="Monitors fatigue and recommends study/break actions to maximise retention.",
            instruction=_INSTRUCTION,
        )
        self.runner = InMemoryRunner(
            agent=self.agent,
            app_name="cramming_crisis_coordinator",
        )

    async def monitor_and_advise(
        self,
        performance_score: float,
        current_topic: str,
        elapsed_mins: int,
        previous_topic: str | None = None,
    ) -> RetentionAdvice:
        """Assess the student's state and return actionable advice."""
        user_message = (
            f"Performance score on recent questions: {performance_score:.0%}\n"
            f"Current topic: {current_topic}\n"
            f"Time spent on this topic so far: {elapsed_mins} minutes\n"
        )
        if previous_topic:
            user_message += f"Previous topic studied: {previous_topic}\n"
        user_message += "\nWhat should the student do next?"

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

        return _parse_advice(response_text, performance_score)

    # Keep backward-compatible sync stub
    def monitor_fatigue(self, performance_score: float) -> RetentionAdvice:
        if performance_score < 0.5:
            return RetentionAdvice(action="Break", message="Take 5! Your brain needs to settle.")
        return RetentionAdvice(action="Review", message="Quick check-in on the last topic.")


def _parse_advice(raw: str, performance_score: float) -> RetentionAdvice:
    """Parse JSON advice from LLM response."""
    try:
        clean = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        data: dict[str, Any] = json.loads(clean)
        return RetentionAdvice(
            action=data.get("action", "Keep Going"),
            message=data.get("message", "You're doing great, keep it up!"),
            target_topic=data.get("target_topic"),
            suggested_duration_mins=data.get("suggested_duration_mins"),
        )
    except Exception:
        # Graceful fallback
        if performance_score < 0.4:
            return RetentionAdvice(
                action="Break",
                message="Take a 5-minute breather. Your brain is working hard!",
                suggested_duration_mins=5,
            )
        return RetentionAdvice(
            action="Keep Going",
            message="You're on a roll! Stay focused.",
        )
