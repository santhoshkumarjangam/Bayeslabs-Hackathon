"""
ChatAgent — Context-aware study assistant.

Fetches the student's full session context (panic state, documents, quiz results,
study plan, sprint progress) and answers questions in a personalised, helpful way.
Maintains conversation history per session.
"""
from __future__ import annotations
import json
from typing import Optional

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

load_dotenv()

_INSTRUCTION = """
You are a personalized AI study tutor for a student cramming for an exam.

You will be given:
1. The student's panic state and exam context
2. Their uploaded study notes/documents
3. Their diagnostic quiz results (which topics they got wrong)
4. Their adaptive study plan (topics + sprints)
5. Their sprint quiz results (if any)
6. The current conversation history

Use ALL of this context to give highly personalized, concise, exam-focused answers.

Guidelines:
- Always relate your answers back to their notes/context if relevant
- If they ask about a topic they scored poorly on, be extra thorough
- If they ask about a topic they scored well on, be encouraging but brief
- Keep answers focused — they are cramming, not doing deep reading
- Use bullet points for lists, formulas clearly marked
- Suggest they start the relevant sprint if they haven't done it yet
- Be warm but efficient — every minute counts before their exam
"""


class ChatAgent:
    def __init__(self):
        self.agent = Agent(
            name="ChatTutor",
            model="gemini-2.5-flash",
            description="Context-aware study chat assistant that knows the student's session.",
            instruction=_INSTRUCTION,
        )
        self.runner = InMemoryRunner(
            agent=self.agent,
            app_name="cramming_crisis_coordinator",
        )
        # In-memory chat history per session_id
        # { session_id: adk_session_id }
        self._session_map: dict[str, str] = {}

    async def chat(
        self,
        session_id: str,
        user_message: str,
        context: str,
    ) -> str:
        """
        Send a message and get a context-aware response.
        Conversation history is maintained across calls with the same session_id.
        """
        # Create or reuse ADK session for this study session
        if session_id not in self._session_map:
            adk_session = await self.runner.session_service.create_session(
                app_name="cramming_crisis_coordinator",
                user_id=session_id,
            )
            self._session_map[session_id] = adk_session.id

            # Prime the session with full student context on first message
            primer = (
                "=== STUDENT CONTEXT ===\n"
                f"{context}\n"
                "=== END CONTEXT ===\n\n"
                "You now have full context about this student. "
                "Answer their questions using this information."
            )
            async for event in self.runner.run_async(
                user_id=session_id,
                session_id=self._session_map[session_id],
                new_message=genai_types.Content(
                    role="user",
                    parts=[genai_types.Part(text=primer)],
                ),
            ):
                if event.is_final_response():
                    break  # discard primer response

        # Send the actual user message
        response_text = ""
        async for event in self.runner.run_async(
            user_id=session_id,
            session_id=self._session_map[session_id],
            new_message=genai_types.Content(
                role="user",
                parts=[genai_types.Part(text=user_message)],
            ),
        ):
            if event.is_final_response() and event.content and event.content.parts:
                response_text = event.content.parts[0].text
                break

        return response_text or "Sorry, I couldn't generate a response. Please try again."

    def clear_session(self, session_id: str) -> None:
        """Remove chat history for a session (e.g. on session completion)."""
        self._session_map.pop(session_id, None)
