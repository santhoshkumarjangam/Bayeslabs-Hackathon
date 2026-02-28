"""
SprintQuizEvaluatorAgent — Evaluates a student's sprint quiz submission.
Compares answers against stored correct answers and generates
personalised, actionable feedback on each wrong answer.
"""
from __future__ import annotations
import json
import re
from typing import Any

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

load_dotenv()


_INSTRUCTION = """
You are a compassionate but rigorous exam tutor. You receive a student's quiz results
for a specific topic and provide detailed, actionable feedback.

Given:
- The topic studied
- Each question with the correct answer and the student's answer
- Explanations for each correct answer

Your job:
1. For each WRONG answer: explain what the student misunderstood (1-2 sentences)
2. Give a concise "what to revise" recommendation for each gap
3. Provide an overall evaluation (2-3 sentences): what the student knows well vs. still needs work
4. Give a confidence score 0.0–1.0 for whether the student is ready for this topic

Return ONLY valid JSON — no markdown, no code fences:
{
  "overall_feedback": "<2-3 sentence summary of performance>",
  "confidence_score": <0.0–1.0>,
  "ready_for_exam": <true|false>,
  "question_feedback": [
    {
      "question_id": "sq1",
      "is_correct": <true|false>,
      "misconception": "<what they got wrong — only if incorrect, else null>",
      "revision_tip": "<what to review — only if incorrect, else null>"
    },
    ...
  ],
  "recommended_action": "keep_going|review_topic|rest_and_retry"
}
"""


class SprintQuizEvaluatorAgent:
    def __init__(self):
        self.agent = Agent(
            name="SprintQuizEvaluator",
            model="gemini-2.5-flash",
            description="Evaluates sprint quiz answers and provides actionable feedback.",
            instruction=_INSTRUCTION,
        )
        self.runner = InMemoryRunner(
            agent=self.agent,
            app_name="cramming_crisis_coordinator",
        )

    async def evaluate(
        self,
        topic: str,
        scored_answers: list[dict],  # {question_id, question, correct_answer, selected, is_correct, explanation}
        score: float,
    ) -> dict:
        """
        Generate personalised feedback for a sprint quiz submission.
        Returns a dict matching the JSON schema above.
        """
        answers_text = json.dumps(scored_answers, indent=2)
        user_message = (
            f"Topic: {topic}\n"
            f"Score: {score:.0%} ({sum(1 for a in scored_answers if a['is_correct'])} / {len(scored_answers)} correct)\n\n"
            f"Student's answers:\n{answers_text}\n\n"
            "Evaluate the performance and provide detailed feedback."
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

        return _parse_evaluation(response_text, scored_answers, score)


def _parse_evaluation(raw: str, scored_answers: list[dict], score: float) -> dict:
    try:
        clean = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        return json.loads(clean)
    except Exception:
        # Fallback: minimal evaluation
        correct = sum(1 for a in scored_answers if a["is_correct"])
        total = len(scored_answers)
        return {
            "overall_feedback": (
                f"You scored {score:.0%} ({correct}/{total}). "
                "Review the incorrect answers and study the explanations before your exam."
                if score < 0.7 else
                f"Well done! {score:.0%} — you have a solid grasp of this topic."
            ),
            "confidence_score": round(score, 2),
            "ready_for_exam": score >= 0.7,
            "question_feedback": [
                {
                    "question_id": a["question_id"],
                    "is_correct": a["is_correct"],
                    "misconception": None if a["is_correct"] else "Review the explanation for this question.",
                    "revision_tip": None if a["is_correct"] else f"Re-read the content on {a.get('topic', 'this topic')}.",
                }
                for a in scored_answers
            ],
            "recommended_action": "keep_going" if score >= 0.8 else "review_topic" if score >= 0.5 else "rest_and_retry",
        }
