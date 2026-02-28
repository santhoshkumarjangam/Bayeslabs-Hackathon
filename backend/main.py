"""
Cramming Crisis Coordinator API  v4.0
SQLite-backed, 2-step quiz-driven pipeline.

Flow:
  POST /start        → Upload notes + message → DiagnosticQuiz (saved to DB)
  POST /quiz/submit  → Student answers → Score → Adaptive StudyPlan (saved to DB)
  POST /clarify      → "I still don't get X" → Targeted micro-sprints
  POST /session/feedback → Fatigue/retention advice after each sprint
  GET  /sessions     → List all past sessions
  GET  /sessions/{id} → Get full session details (quiz + plan)
"""
from __future__ import annotations

import json
import os
import uuid
from collections import defaultdict
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from agents.panic_intake import PanicIntakeAgent
from agents.prioritization import PrioritizationAgent
from agents.orchestrator import OrchestratorAgent
from agents.retention import RetentionBoosterAgent
from agents.clarify import ClarifyAgent
from agents.quiz_agent import QuizAgent
from agents.document_extractor import extract_text_from_upload
from agents.schemas import (
    DiagnosticQuiz,
    PanicState,
    QuizQuestion,
    QuizResult,
    QuizSubmission,
    RetentionAdvice,
    SprintSession,
    StudyPlan,
    TopicScore,
    PrioritizedTopic,
)
from database import get_db, init_db
from document_service import router as documents_router
from models import (
    DocumentRecord,
    QuizQuestionRecord,
    QuizSubmissionRecord,
    SessionRecord,
    SprintSessionRecord,
    StudyPlanRecord,
)

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Cramming Crisis Coordinator API",
    description=(
        "Multi-agent AI swarm for last-minute exam prep.\n\n"
        "**Flow:**\n"
        "1. `POST /start` → upload notes + describe situation → get diagnostic quiz\n"
        "2. `POST /quiz/submit` → answer quiz → get adaptive sprint study plan\n"
        "3. `POST /clarify` → *I still don't get X* → targeted micro-sprints\n"
        "4. `POST /session/feedback` → post-sprint fatigue check"
    ),
    version="4.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────────────────────
# DB init on startup
# ─────────────────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def on_startup():
    await init_db()

# Mount sub-routers
app.include_router(documents_router)

# ─────────────────────────────────────────────────────────────────────────────
# Agent singletons
# ─────────────────────────────────────────────────────────────────────────────

intake_agent = PanicIntakeAgent()
prioritizer = PrioritizationAgent()
orchestrator = OrchestratorAgent()
retention_agent = RetentionBoosterAgent()
clarify_agent = ClarifyAgent()
quiz_agent = QuizAgent()

# ─────────────────────────────────────────────────────────────────────────────
# Request schemas
# ─────────────────────────────────────────────────────────────────────────────

class ClarifyRequest(BaseModel):
    confused_topic: str
    context: Optional[str] = None


class FeedbackRequest(BaseModel):
    performance_score: float
    current_topic: str
    elapsed_mins: int
    previous_topic: Optional[str] = None


class StartRequest(BaseModel):
    message: str
    document_ids: Optional[List[str]] = None
    num_questions: int = 10

    model_config = {
        "json_schema_extra": {
            "example": {
                "message": "I have a Machine Learning exam in 4 hours. Weak on backpropagation and CNNs.",
                "document_ids": ["<uuid from POST /documents/upload>"],
                "num_questions": 10,
            }
        }
    }

# ─────────────────────────────────────────────────────────────────────────────
# Response schemas (lightweight — for list views)
# ─────────────────────────────────────────────────────────────────────────────

class SessionSummary(BaseModel):
    session_id: str
    status: str
    panic_level: int
    topics: List[str]
    time_available_hours: float
    created_at: str
    overall_score: Optional[float] = None


class SessionDetail(BaseModel):
    session_id: str
    status: str
    panic_level: int
    topics: List[str]
    time_available_hours: float
    urgency_reason: Optional[str]
    summary: str
    created_at: str
    questions: List[QuizQuestion]
    study_plan: Optional[StudyPlan] = None
    overall_score: Optional[float] = None
    weak_topics: List[str] = []
    strong_topics: List[str] = []

# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/", tags=["Health"])
async def root():
    return {"message": "Swarm is ready to coordinate your panic.", "status": "ok"}


@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "healthy" if os.getenv("GOOGLE_API_KEY") else "degraded",
        "google_api_key_configured": bool(os.getenv("GOOGLE_API_KEY")),
        "agents": ["PanicIntake", "QuizAgent", "Prioritizer", "Orchestrator", "RetentionBooster", "Clarify"],
        "database": "SQLite (cramming_crisis.db)",
        "version": "4.0.0",
    }


# ── STEP 1 ───────────────────────────────────────────────────────────────────

@app.post("/start", response_model=DiagnosticQuiz, tags=["Step 1 – Quiz"])
async def start_session(
    body: StartRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    **STEP 1** — Start a study session with a JSON payload.

    Provide your situation message and optionally reference pre-uploaded
    document IDs (from `POST /documents/upload`). The agent reads the
    notes text directly from the database — no file re-upload needed.

    Returns a `DiagnosticQuiz`. Use the `session_id` to submit answers.
    """
    notes_parts: list[str] = []
    linked_docs: list[DocumentRecord] = []

    # Fetch pre-uploaded documents from DB by ID
    if body.document_ids:
        for doc_id in body.document_ids:
            result = await db.execute(
                select(DocumentRecord).where(DocumentRecord.id == doc_id)
            )
            doc = result.scalar_one_or_none()
            if doc is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Document '{doc_id}' not found. Upload via POST /documents/upload first.",
                )
            notes_parts.append(f"[{doc.filename}]\n{doc.raw_text}")
            linked_docs.append(doc)

    notes_text = "\n\n".join(notes_parts)
    full_input = body.message
    if notes_text:
        full_input += f"\n\n--- Notes ---\n{notes_text[:4000]}"

    # Agent: parse student's panic state
    panic_state = await intake_agent.parse_student_input(full_input)

    # Agent: generate diagnostic quiz
    num_q = max(3, min(body.num_questions, 20))
    questions = await quiz_agent.generate_quiz(
        panic_state=panic_state,
        notes_text=notes_text or body.message,
        num_questions=num_q,
    )

    if not questions:
        raise HTTPException(status_code=500, detail="Quiz generation failed. Please try again.")

    # ── Persist to DB ──
    session_id = str(uuid.uuid4())

    db_session = SessionRecord(
        id=session_id,
        status="quiz_pending",
        panic_level=panic_state.panic_level,
        time_available_hours=panic_state.time_available_hours,
        urgency_reason=panic_state.urgency_reason,
        summary=panic_state.summary,
        extracted_text=panic_state.extracted_text[:5000],
        notes_text=notes_text[:10000] if notes_text else "",
    )
    db_session.set_topics(panic_state.topics_mentioned)
    db_session.documents.extend(linked_docs)
    db.add(db_session)

    for q in questions:
        db_q = QuizQuestionRecord(
            session_id=session_id,
            question_id=q.id,
            topic=q.topic,
            question=q.question,
            correct_answer=q.correct_answer,
            difficulty=q.difficulty,
        )
        db_q.set_choices(q.choices)
        db.add(db_q)

    await db.commit()

    return DiagnosticQuiz(
        session_id=session_id,
        panic_state=panic_state,
        questions=questions,
        instructions=(
            f"Answer all {len(questions)} questions — even guessing is fine. "
            "Your answers reveal your weak spots and shape your personal study plan. "
            "Submit via POST /quiz/submit with this session_id."
        ),
    )


# ── STEP 2 ───────────────────────────────────────────────────────────────────

@app.post("/quiz/submit", response_model=QuizResult, tags=["Step 2 – Score & Study Plan"])
async def submit_quiz(
    submission: QuizSubmission,
    db: AsyncSession = Depends(get_db),
):
    """
    **STEP 2** — Submit quiz answers.
    Scores per topic, identifies weak spots, generates adaptive sprint plan.
    Everything is persisted to the database.
    """
    # Load session + questions from DB
    result = await db.execute(
        select(SessionRecord)
        .options(selectinload(SessionRecord.questions))
        .where(SessionRecord.id == submission.session_id)
    )
    db_session = result.scalar_one_or_none()

    if not db_session:
        raise HTTPException(status_code=404, detail="Session not found. Call POST /start first.")
    if db_session.status != "quiz_pending":
        raise HTTPException(status_code=409, detail=f"Quiz already submitted (status: {db_session.status}).")

    # Build question lookup
    q_map = {q.question_id: q for q in db_session.questions}

    # Score per topic
    topic_correct: dict[str, int] = defaultdict(int)
    topic_total: dict[str, int] = defaultdict(int)

    for answer in submission.answers:
        db_q = q_map.get(answer.question_id)
        if not db_q:
            continue
        is_correct = answer.selected.upper().strip() == db_q.correct_answer.upper().strip()
        topic_total[db_q.topic] += 1
        if is_correct:
            topic_correct[db_q.topic] += 1

        # Persist answer
        db.add(QuizSubmissionRecord(
            session_id=submission.session_id,
            question_id=answer.question_id,
            topic=db_q.topic,
            selected_answer=answer.selected.upper().strip(),
            correct_answer=db_q.correct_answer,
            is_correct=is_correct,
        ))

    # Compute scores
    topic_scores: List[TopicScore] = []
    for topic, total in topic_total.items():
        correct = topic_correct.get(topic, 0)
        topic_scores.append(TopicScore(topic=topic, score=correct / total, correct=correct, total=total))

    overall_score = (
        sum(ts.correct for ts in topic_scores) / sum(ts.total for ts in topic_scores)
        if topic_scores else 0.0
    )
    weak_topics = [ts.topic for ts in topic_scores if ts.score < 0.5]
    strong_topics = [ts.topic for ts in topic_scores if ts.score >= 0.75]

    # Rebuild PanicState for the agents (focused on weak spots)
    original_topics = db_session.get_topics()
    focused_panic = PanicState(
        panic_level=db_session.panic_level,
        extracted_text=db_session.extracted_text,
        topics_mentioned=weak_topics if weak_topics else original_topics,
        time_available_hours=db_session.time_available_hours,
        urgency_reason=db_session.urgency_reason,
        summary=(
            f"After the diagnostic quiz, student scored {overall_score:.0%}. "
            f"Weak on: {', '.join(weak_topics) if weak_topics else 'nothing — great!'}. "
            f"Strong on: {', '.join(strong_topics) if strong_topics else 'nothing yet'}. "
            f"Original context: {db_session.summary}"
        ),
    )

    # Agents: build adaptive plan from weak topics
    prioritized = await prioritizer.prioritize(focused_panic)
    sprints = await orchestrator.create_sprint_plan(
        topics=prioritized,
        time_available_hours=db_session.time_available_hours,
    )
    total_mins = sum(s.duration_mins for s in sprints)

    if weak_topics:
        note = (
            f"You scored {overall_score:.0%}. Study plan targets: {', '.join(weak_topics)}. "
            f"{len(sprints)} sprints, {total_mins} mins total. Let's fix these gaps! 🔥"
        )
    else:
        note = (
            f"Impressive! {overall_score:.0%} on the diagnostic. "
            f"Here's a solid review plan to lock it all in. 💪"
        )

    # Persist study plan
    db_plan = StudyPlanRecord(
        session_id=submission.session_id,
        overall_score=overall_score,
        total_study_mins=total_mins,
        motivational_note=note,
    )
    db_plan.set_weak_topics(weak_topics)
    db_plan.set_strong_topics(strong_topics)
    db.add(db_plan)
    await db.flush()  # get db_plan.id

    for s in sprints:
        db_sprint = SprintSessionRecord(
            study_plan_id=db_plan.id,
            sprint_number=s.sprint_number,
            topic=s.topic,
            duration_mins=s.duration_mins,
            activity_type=s.activity_type,
            tips=s.tips,
        )
        db_sprint.set_content(s.content)
        db_sprint.set_questions(s.questions)
        db.add(db_sprint)

    # Update session status
    db_session.status = "plan_generated"
    await db.commit()

    study_plan = StudyPlan(
        panic_state=focused_panic,
        prioritized_topics=prioritized,
        sprint_plan=sprints,
        total_study_mins=total_mins,
        motivational_note=note,
    )

    return QuizResult(
        overall_score=overall_score,
        topic_scores=topic_scores,
        weak_topics=weak_topics,
        strong_topics=strong_topics,
        study_plan=study_plan,
    )


# ── ADAPTIVE ─────────────────────────────────────────────────────────────────

@app.post("/clarify", response_model=List[SprintSession], tags=["Adaptive"])
async def clarify_topic(request: ClarifyRequest):
    """
    **Mid-session: "I still don't get X"**
    Returns 1–3 targeted micro-sprints that break the confusion into smallest pieces.
    """
    if not request.confused_topic.strip():
        raise HTTPException(status_code=400, detail="confused_topic cannot be empty.")
    return await clarify_agent.clarify_topic(
        confused_topic=request.confused_topic,
        student_context=request.context or "",
    )


# ── MONITORING ───────────────────────────────────────────────────────────────

@app.post("/session/feedback", response_model=RetentionAdvice, tags=["Monitoring"])
async def session_feedback(request: FeedbackRequest):
    """
    **After each sprint** — submit performance score + elapsed time.
    Retention Booster advises: keep going, break, switch topic, or review.
    """
    if not 0.0 <= request.performance_score <= 1.0:
        raise HTTPException(status_code=400, detail="performance_score must be 0.0–1.0")
    return await retention_agent.monitor_and_advise(
        performance_score=request.performance_score,
        current_topic=request.current_topic,
        elapsed_mins=request.elapsed_mins,
        previous_topic=request.previous_topic,
    )


# ── HISTORY ──────────────────────────────────────────────────────────────────

@app.get("/sessions", response_model=List[SessionSummary], tags=["History"])
async def list_sessions(db: AsyncSession = Depends(get_db)):
    """List all recorded sessions (newest first)."""
    result = await db.execute(
        select(SessionRecord)
        .options(selectinload(SessionRecord.study_plan))
        .order_by(SessionRecord.created_at.desc())
    )
    records = result.scalars().all()
    return [
        SessionSummary(
            session_id=r.id,
            status=r.status,
            panic_level=r.panic_level,
            topics=r.get_topics(),
            time_available_hours=r.time_available_hours,
            created_at=r.created_at.isoformat(),
            overall_score=r.study_plan.overall_score if r.study_plan else None,
        )
        for r in records
    ]


@app.get("/sessions/{session_id}", response_model=SessionDetail, tags=["History"])
async def get_session(session_id: str, db: AsyncSession = Depends(get_db)):
    """Get full details for a session: quiz questions + study plan + sprints."""
    result = await db.execute(
        select(SessionRecord)
        .options(
            selectinload(SessionRecord.questions),
            selectinload(SessionRecord.study_plan).selectinload(StudyPlanRecord.sprints),
        )
        .where(SessionRecord.id == session_id)
    )
    rec = result.scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="Session not found.")

    questions = [
        QuizQuestion(
            id=q.question_id,
            topic=q.topic,
            question=q.question,
            choices=q.get_choices(),
            correct_answer=q.correct_answer,
            difficulty=q.difficulty,
        )
        for q in rec.questions
    ]

    study_plan = None
    if rec.study_plan:
        sp = rec.study_plan
        sprint_list = [
            SprintSession(
                sprint_number=s.sprint_number,
                topic=s.topic,
                duration_mins=s.duration_mins,
                activity_type=s.activity_type,
                questions=s.get_questions(),
                tips=s.tips,
            )
            for s in sp.sprints
        ]
        panic = PanicState(
            panic_level=rec.panic_level,
            extracted_text=rec.extracted_text,
            topics_mentioned=sp.get_weak_topics() or rec.get_topics(),
            time_available_hours=rec.time_available_hours,
            urgency_reason=rec.urgency_reason,
            summary=rec.summary,
        )
        study_plan = StudyPlan(
            panic_state=panic,
            prioritized_topics=[
                PrioritizedTopic(topic=t, priority=10, estimated_time_mins=15, yield_type="High Yield")
                for t in sp.get_weak_topics()
            ],
            sprint_plan=sprint_list,
            total_study_mins=sp.total_study_mins,
            motivational_note=sp.motivational_note,
        )

    return SessionDetail(
        session_id=rec.id,
        status=rec.status,
        panic_level=rec.panic_level,
        topics=rec.get_topics(),
        time_available_hours=rec.time_available_hours,
        urgency_reason=rec.urgency_reason,
        summary=rec.summary,
        created_at=rec.created_at.isoformat(),
        questions=questions,
        study_plan=study_plan,
        overall_score=rec.study_plan.overall_score if rec.study_plan else None,
        weak_topics=rec.study_plan.get_weak_topics() if rec.study_plan else [],
        strong_topics=rec.study_plan.get_strong_topics() if rec.study_plan else [],
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
