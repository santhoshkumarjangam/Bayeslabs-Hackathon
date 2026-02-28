"""
Shared Pydantic schemas for the Cramming Crisis Coordinator agent pipeline.
"""
from __future__ import annotations
from typing import List, Optional
import pydantic


# ---------------------------------------------------------------------------
# Intake
# ---------------------------------------------------------------------------

class PanicState(pydantic.BaseModel):
    panic_level: int = 5          # 1–10
    extracted_text: str = ""
    topics_mentioned: List[str] = []
    time_available_hours: float = 4.0
    urgency_reason: Optional[str] = None
    summary: str = ""


# ---------------------------------------------------------------------------
# Prioritization
# ---------------------------------------------------------------------------

class PrioritizedTopic(pydantic.BaseModel):
    topic: str
    priority: int                  # 1–10, 10 = most important
    estimated_time_mins: int
    yield_type: str                # "High Yield" | "Foundational" | "Quick Win"


# ---------------------------------------------------------------------------
# Orchestration / Sprint Plan
# ---------------------------------------------------------------------------

class SprintSession(pydantic.BaseModel):
    sprint_number: int
    topic: str
    duration_mins: int
    activity_type: str             # "Active Recall" | "Flashcards" | "Blurting"
    questions: List[str]
    tips: Optional[str] = None
    content: List[str] = []        # bullet-point study notes / key concepts to review


# ---------------------------------------------------------------------------
# Retention / Fatigue Monitoring
# ---------------------------------------------------------------------------

class RetentionAdvice(pydantic.BaseModel):
    action: str                    # "Review" | "Break" | "Sleep" | "Switch Topic" | "Keep Going"
    message: str
    target_topic: Optional[str] = None
    suggested_duration_mins: Optional[int] = None


# ---------------------------------------------------------------------------
# Full Study Plan (what /intake returns to the frontend)
# ---------------------------------------------------------------------------

class StudyPlan(pydantic.BaseModel):
    panic_state: PanicState
    prioritized_topics: List[PrioritizedTopic]
    sprint_plan: List[SprintSession]
    total_study_mins: int
    motivational_note: str


# ---------------------------------------------------------------------------
# Diagnostic Quiz (Step 1 output / Step 2 input)
# ---------------------------------------------------------------------------

class QuizQuestion(pydantic.BaseModel):
    id: str                        # e.g. "q1", "q2"
    topic: str                     # which topic this question tests
    question: str
    choices: List[str]             # exactly 4 choices ["A) ...", "B) ...", ...]
    correct_answer: str            # "A", "B", "C", or "D"
    difficulty: str = "medium"     # "easy" | "medium" | "hard"


class DiagnosticQuiz(pydantic.BaseModel):
    session_id: str
    panic_state: PanicState
    questions: List[QuizQuestion]
    instructions: str


class QuizAnswer(pydantic.BaseModel):
    question_id: str               # matches QuizQuestion.id
    selected: str                  # "A", "B", "C", or "D"


class QuizSubmission(pydantic.BaseModel):
    session_id: str
    answers: List[QuizAnswer]


class TopicScore(pydantic.BaseModel):
    topic: str
    score: float                   # 0.0–1.0
    correct: int
    total: int


class QuizResult(pydantic.BaseModel):
    overall_score: float           # 0.0–1.0
    topic_scores: List[TopicScore]
    weak_topics: List[str]         # scored < 0.5
    strong_topics: List[str]       # scored >= 0.75
    study_plan: StudyPlan          # the adaptive plan built from weak spots

