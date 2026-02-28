"""
chat_service.py — Context-aware student chat.

Fetches the full student session context from the DB (panic state, documents,
study plan, quiz results) and routes messages through the ChatAgent which
maintains conversation history throughout the session.

Endpoints:
  POST /chat            → send a message, get a context-aware AI reply
  DELETE /chat/{id}     → clear conversation history for a session
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from agents.chat_agent import ChatAgent
from database import get_db
from models import (
    DocumentRecord,
    SessionRecord,
    SprintQuizAttempt,
    StudyPlanRecord,
)

router = APIRouter(prefix="/chat", tags=["Chat"])

# Singleton — keeps conversation history in memory
_chat_agent = ChatAgent()


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic schemas
# ─────────────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    session_id: str
    message: str

    model_config = {
        "json_schema_extra": {
            "example": {
                "session_id": "<uuid from POST /start>",
                "message": "I still don't understand backpropagation. Can you explain the chain rule part simply?",
            }
        }
    }


class ChatResponse(BaseModel):
    session_id: str
    message: str      # student's message (echoed back)
    reply: str        # AI tutor's response


# ─────────────────────────────────────────────────────────────────────────────
# Context builder — assembles student context from DB
# ─────────────────────────────────────────────────────────────────────────────

async def _build_context(session_id: str, db: AsyncSession) -> str:
    """
    Fetches the full student session from DB and formats it as a
    human-readable context string for the ChatAgent.
    """
    # Load session with all related data
    result = await db.execute(
        select(SessionRecord)
        .options(
            selectinload(SessionRecord.questions),
            selectinload(SessionRecord.submissions),
            selectinload(SessionRecord.documents),
            selectinload(SessionRecord.study_plan).selectinload(StudyPlanRecord.sprints),
        )
        .where(SessionRecord.id == session_id)
    )
    rec = result.scalar_one_or_none()
    if not rec:
        return "No session data found."

    lines: list[str] = []

    # ── Panic State ──
    lines.append("## Student Situation")
    lines.append(f"- Panic Level: {rec.panic_level}/10")
    lines.append(f"- Time Available: {rec.time_available_hours} hours")
    lines.append(f"- Urgency: {rec.urgency_reason or 'Not specified'}")
    lines.append(f"- Summary: {rec.summary}")

    # ── Topics ──
    topics = rec.get_topics()
    if topics:
        lines.append(f"\n## Topics Being Studied")
        for t in topics:
            lines.append(f"- {t}")

    # ── Uploaded Documents ──
    if rec.documents:
        lines.append(f"\n## Uploaded Study Materials")
        for doc in rec.documents:
            lines.append(f"### {doc.filename} ({doc.word_count} words)")
            # Include first 1500 chars of each doc
            lines.append(doc.raw_text[:1500])
            if len(doc.raw_text) > 1500:
                lines.append("... [content truncated]")

    # ── Notes text (if uploaded via start directly) ──
    if rec.notes_text and not rec.documents:
        lines.append(f"\n## Uploaded Notes")
        lines.append(rec.notes_text[:2000])

    # ── Diagnostic Quiz Results ──
    if rec.submissions:
        lines.append(f"\n## Diagnostic Quiz Results")
        topic_correct: dict[str, int] = {}
        topic_total: dict[str, int] = {}
        for sub in rec.submissions:
            topic_total[sub.topic] = topic_total.get(sub.topic, 0) + 1
            if sub.is_correct:
                topic_correct[sub.topic] = topic_correct.get(sub.topic, 0) + 1
        for topic, total in topic_total.items():
            correct = topic_correct.get(topic, 0)
            pct = correct / total if total > 0 else 0
            status = "✅ Strong" if pct >= 0.75 else "⚠️ Weak" if pct < 0.5 else "↔️ OK"
            lines.append(f"- {topic}: {correct}/{total} ({pct:.0%}) {status}")

    # ── Study Plan ──
    if rec.study_plan:
        sp = rec.study_plan
        lines.append(f"\n## Adaptive Study Plan")
        lines.append(f"- Overall Diagnostic Score: {sp.overall_score:.0%}")
        lines.append(f"- Weak Topics: {', '.join(sp.get_weak_topics()) or 'None'}")
        lines.append(f"- Strong Topics: {', '.join(sp.get_strong_topics()) or 'None'}")
        lines.append(f"- Total Study Time: {sp.total_study_mins} minutes")
        lines.append(f"- Note: {sp.motivational_note}")

        if sp.sprints:
            lines.append(f"\n## Sprint Plan ({len(sp.sprints)} sprints)")
            for s in sp.sprints:
                lines.append(f"\n### Sprint {s.sprint_number}: {s.topic} ({s.duration_mins} min, {s.activity_type})")
                content = s.get_content()
                if content:
                    lines.append("Key concepts:")
                    for c in content:
                        lines.append(f"  {c}")

                # Check for sprint quiz attempts
                attempts_result = await db.execute(
                    select(SprintQuizAttempt)
                    .where(SprintQuizAttempt.sprint_id == s.id)
                    .order_by(SprintQuizAttempt.submitted_at.desc())
                    .limit(1)
                )
                latest_attempt = attempts_result.scalar_one_or_none()
                if latest_attempt:
                    lines.append(
                        f"  Quiz Result: {latest_attempt.score:.0%} | "
                        f"Ready for exam: {'Yes' if latest_attempt.ready_for_exam else 'No'} | "
                        f"Action: {latest_attempt.recommended_action}"
                    )

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.post("", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    **Context-aware study chat.**

    Ask anything about your notes, topics, study plan, or quiz results.
    The AI tutor knows your full session context and maintains conversation history.

    - "Explain backpropagation from my notes"
    - "Which topics should I prioritize with 2 hours left?"
    - "What did I get wrong in the quiz?"
    - "Give me a quick summary of Sprint 3's content"
    """
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    # Build context from DB (only fetched once — on first message the agent is primed)
    context = await _build_context(body.session_id, db)

    if context == "No session data found.":
        raise HTTPException(
            status_code=404,
            detail="Session not found. Start a session first via POST /start."
        )

    reply = await _chat_agent.chat(
        session_id=body.session_id,
        user_message=body.message,
        context=context,
    )

    return ChatResponse(
        session_id=body.session_id,
        message=body.message,
        reply=reply,
    )


@router.delete("/{session_id}", status_code=204)
async def clear_chat_history(session_id: str):
    """
    Clear the in-memory conversation history for a session.
    The next message will start a fresh conversation (context is re-fetched from DB).
    """
    _chat_agent.clear_session(session_id)
