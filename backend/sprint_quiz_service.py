"""
sprint_quiz_service.py — Topic-wise quiz after completing a sprint.

Flow:
  POST /sprint-quiz/generate  → sprint_id → stores MCQs, returns questions (NO correct answers)
  POST /sprint-quiz/submit    → attempt submission → scores, AI evaluation, returns full results
  GET  /sprint-quiz/{sprint_id}/attempts → list all past attempts for a sprint
  GET  /sprint-quiz/attempt/{attempt_id} → get full attempt with answers + explanations
"""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agents.sprint_quiz_agent import SprintQuizAgent
from agents.sprint_quiz_evaluator import SprintQuizEvaluatorAgent
from database import get_db
from models import (
    SprintQuizAnswer,
    SprintQuizAttempt,
    SprintQuizQuestion,
    SprintSessionRecord,
)

router = APIRouter(prefix="/sprint-quiz", tags=["Sprint Quiz"])

# Agent singletons
_quiz_agent = SprintQuizAgent()
_eval_agent = SprintQuizEvaluatorAgent()


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic schemas
# ─────────────────────────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    sprint_id: int
    num_questions: int = 5

    model_config = {
        "json_schema_extra": {
            "example": {
                "sprint_id": 1,
                "num_questions": 5,
            }
        }
    }


class QuizQuestionOut(BaseModel):
    """Question sent to the client — correct_answer and explanation are HIDDEN."""
    question_db_id: str
    question_id: str
    question: str
    choices: List[str]
    difficulty: str


class GenerateResponse(BaseModel):
    sprint_id: int
    topic: str
    questions: List[QuizQuestionOut]
    instructions: str


class AnswerIn(BaseModel):
    question_db_id: str    # matches QuizQuestionOut.question_db_id
    question_id: str       # "sq1", "sq2" …
    selected: str          # "A"|"B"|"C"|"D"


class SubmitRequest(BaseModel):
    sprint_id: int
    answers: List[AnswerIn]

    model_config = {
        "json_schema_extra": {
            "example": {
                "sprint_id": 1,
                "answers": [
                    {"question_db_id": "<uuid>", "question_id": "sq1", "selected": "B"},
                    {"question_db_id": "<uuid>", "question_id": "sq2", "selected": "A"},
                ],
            }
        }
    }


class QuestionResult(BaseModel):
    question_id: str
    question: str
    selected_answer: str
    correct_answer: str
    is_correct: bool
    explanation: str            # revealed after submission
    misconception: Optional[str] = None
    revision_tip: Optional[str] = None


class AttemptResult(BaseModel):
    attempt_id: str
    sprint_id: int
    topic: str
    score: float
    correct_count: int
    total_count: int
    overall_feedback: str
    confidence_score: float
    ready_for_exam: bool
    recommended_action: str
    question_results: List[QuestionResult]


class AttemptSummary(BaseModel):
    attempt_id: str
    submitted_at: str
    score: float
    correct_count: int
    total_count: int
    ready_for_exam: bool
    recommended_action: str


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/generate", response_model=GenerateResponse, status_code=201)
async def generate_sprint_quiz(
    body: GenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    **Generate a topic-wise quiz for a completed sprint.**

    Call this when the student finishes a sprint. The correct answers are stored
    in the database but NOT returned — the student sees only questions and choices.
    Submit answers via `POST /sprint-quiz/submit`.
    """
    # Load sprint from DB
    result = await db.execute(
        select(SprintSessionRecord).where(SprintSessionRecord.id == body.sprint_id)
    )
    sprint = result.scalar_one_or_none()
    if not sprint:
        raise HTTPException(status_code=404, detail=f"Sprint {body.sprint_id} not found.")

    num_q = max(3, min(body.num_questions, 10))
    content = sprint.get_content()

    # Agent: generate questions
    raw_questions = await _quiz_agent.generate_sprint_quiz(
        topic=sprint.topic,
        content=content,
        num_questions=num_q,
    )

    if not raw_questions:
        raise HTTPException(status_code=500, detail="Quiz generation failed. Please try again.")

    # Persist to DB (correct_answer stored securely, not returned to client)
    db_questions: list[SprintQuizQuestion] = []
    for q in raw_questions:
        db_q = SprintQuizQuestion(
            sprint_id=body.sprint_id,
            question_id=q["question_id"],
            question=q["question"],
            correct_answer=q["correct_answer"],
            explanation=q["explanation"],
            difficulty=q["difficulty"],
        )
        db_q.set_choices(q["choices"])
        db.add(db_q)
        db_questions.append(db_q)

    await db.commit()
    # Refresh to get generated IDs
    for db_q in db_questions:
        await db.refresh(db_q)

    client_questions = [
        QuizQuestionOut(
            question_db_id=db_q.id,
            question_id=db_q.question_id,
            question=db_q.question,
            choices=db_q.get_choices(),
            difficulty=db_q.difficulty,
        )
        for db_q in db_questions
    ]

    return GenerateResponse(
        sprint_id=body.sprint_id,
        topic=sprint.topic,
        questions=client_questions,
        instructions=(
            f"Answer all {len(client_questions)} questions on '{sprint.topic}'. "
            "Correct answers and explanations are revealed after you submit. "
            "Submit via POST /sprint-quiz/submit."
        ),
    )


@router.post("/submit", response_model=AttemptResult)
async def submit_sprint_quiz(
    body: SubmitRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    **Submit sprint quiz answers.**

    Answers are scored against the stored correct answers.
    An AI agent evaluates the results and provides:
    - Per-question explanation (revealed now)
    - Misconception analysis for wrong answers
    - Confidence score + recommended next action
    """
    # Load sprint
    sprint_result = await db.execute(
        select(SprintSessionRecord).where(SprintSessionRecord.id == body.sprint_id)
    )
    sprint = sprint_result.scalar_one_or_none()
    if not sprint:
        raise HTTPException(status_code=404, detail=f"Sprint {body.sprint_id} not found.")

    # Load questions by their DB ids
    q_ids = [a.question_db_id for a in body.answers]
    q_result = await db.execute(
        select(SprintQuizQuestion).where(SprintQuizQuestion.id.in_(q_ids))
    )
    db_questions = {q.id: q for q in q_result.scalars().all()}

    if not db_questions:
        raise HTTPException(
            status_code=404,
            detail="No matching questions found. Generate a quiz first via POST /sprint-quiz/generate."
        )

    # Score answers
    scored: list[dict] = []
    correct_count = 0

    # Create attempt record
    attempt = SprintQuizAttempt(
        sprint_id=body.sprint_id,
        total_count=len(body.answers),
    )
    db.add(attempt)
    await db.flush()  # get attempt.id

    for ans in body.answers:
        db_q = db_questions.get(ans.question_db_id)
        if not db_q:
            continue
        is_correct = ans.selected.upper().strip() == db_q.correct_answer.upper().strip()
        if is_correct:
            correct_count += 1

        # Persist answer
        db.add(SprintQuizAnswer(
            attempt_id=attempt.id,
            question_db_id=db_q.id,
            question_id=ans.question_id,
            selected_answer=ans.selected.upper().strip(),
            correct_answer=db_q.correct_answer,
            is_correct=is_correct,
        ))

        scored.append({
            "question_id": ans.question_id,
            "question": db_q.question,
            "topic": sprint.topic,
            "correct_answer": db_q.correct_answer,
            "selected": ans.selected.upper().strip(),
            "is_correct": is_correct,
            "explanation": db_q.explanation,
        })

    score = correct_count / len(scored) if scored else 0.0

    # AI evaluation
    evaluation = await _eval_agent.evaluate(
        topic=sprint.topic,
        scored_answers=scored,
        score=score,
    )

    # Update attempt with evaluation
    attempt.score = score
    attempt.correct_count = correct_count
    attempt.total_count = len(scored)
    attempt.overall_feedback = evaluation.get("overall_feedback", "")
    attempt.confidence_score = evaluation.get("confidence_score", score)
    attempt.ready_for_exam = evaluation.get("ready_for_exam", score >= 0.7)
    attempt.recommended_action = evaluation.get("recommended_action", "review_topic")
    attempt.set_question_feedback(evaluation.get("question_feedback", []))

    await db.commit()

    # Build per-question result (correct_answer + explanation NOW revealed)
    q_feedback_map = {
        f["question_id"]: f
        for f in evaluation.get("question_feedback", [])
    }

    question_results = []
    for s in scored:
        fb = q_feedback_map.get(s["question_id"], {})
        question_results.append(QuestionResult(
            question_id=s["question_id"],
            question=s["question"],
            selected_answer=s["selected"],
            correct_answer=s["correct_answer"],
            is_correct=s["is_correct"],
            explanation=s["explanation"],
            misconception=fb.get("misconception") if not s["is_correct"] else None,
            revision_tip=fb.get("revision_tip") if not s["is_correct"] else None,
        ))

    return AttemptResult(
        attempt_id=attempt.id,
        sprint_id=body.sprint_id,
        topic=sprint.topic,
        score=score,
        correct_count=correct_count,
        total_count=len(scored),
        overall_feedback=attempt.overall_feedback,
        confidence_score=attempt.confidence_score,
        ready_for_exam=attempt.ready_for_exam,
        recommended_action=attempt.recommended_action,
        question_results=question_results,
    )


@router.get("/{sprint_id}/attempts", response_model=List[AttemptSummary])
async def list_attempts(sprint_id: int, db: AsyncSession = Depends(get_db)):
    """List all quiz attempts for a sprint (newest first)."""
    result = await db.execute(
        select(SprintQuizAttempt)
        .where(SprintQuizAttempt.sprint_id == sprint_id)
        .order_by(SprintQuizAttempt.submitted_at.desc())
    )
    attempts = result.scalars().all()
    return [
        AttemptSummary(
            attempt_id=a.id,
            submitted_at=a.submitted_at.isoformat(),
            score=a.score,
            correct_count=a.correct_count,
            total_count=a.total_count,
            ready_for_exam=a.ready_for_exam,
            recommended_action=a.recommended_action,
        )
        for a in attempts
    ]


@router.get("/attempt/{attempt_id}", response_model=AttemptResult)
async def get_attempt(attempt_id: str, db: AsyncSession = Depends(get_db)):
    """Retrieve full attempt details with per-question results and explanations."""
    result = await db.execute(
        select(SprintQuizAttempt)
        .options(selectinload(SprintQuizAttempt.answers).selectinload(SprintQuizAnswer.question))
        .where(SprintQuizAttempt.id == attempt_id)
    )
    attempt = result.scalar_one_or_none()
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found.")

    # Load sprint for topic
    sprint_result = await db.execute(
        select(SprintSessionRecord).where(SprintSessionRecord.id == attempt.sprint_id)
    )
    sprint = sprint_result.scalar_one_or_none()
    topic = sprint.topic if sprint else "Unknown"

    q_feedback_map = {
        f["question_id"]: f
        for f in attempt.get_question_feedback()
    }

    question_results = [
        QuestionResult(
            question_id=ans.question_id,
            question=ans.question.question,
            selected_answer=ans.selected_answer,
            correct_answer=ans.correct_answer,
            is_correct=ans.is_correct,
            explanation=ans.question.explanation,
            misconception=q_feedback_map.get(ans.question_id, {}).get("misconception") if not ans.is_correct else None,
            revision_tip=q_feedback_map.get(ans.question_id, {}).get("revision_tip") if not ans.is_correct else None,
        )
        for ans in attempt.answers
    ]

    return AttemptResult(
        attempt_id=attempt.id,
        sprint_id=attempt.sprint_id,
        topic=topic,
        score=attempt.score,
        correct_count=attempt.correct_count,
        total_count=attempt.total_count,
        overall_feedback=attempt.overall_feedback,
        confidence_score=attempt.confidence_score,
        ready_for_exam=attempt.ready_for_exam,
        recommended_action=attempt.recommended_action,
        question_results=question_results,
    )
