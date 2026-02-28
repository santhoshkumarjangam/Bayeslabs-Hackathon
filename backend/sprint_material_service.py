"""
sprint_material_service.py — Generates and returns 1-2 pages of detailed
markdown study material for a specific sprint, using the student's original context.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from agents.sprint_material_agent import SprintMaterialAgent
from database import get_db
from models import SprintSessionRecord, StudyPlanRecord, SessionRecord

router = APIRouter(prefix="/sprint-material", tags=["Sprint Material"])

_material_agent = SprintMaterialAgent()


class SprintMaterialResponse(BaseModel):
    sprint_id: int
    topic: str
    detailed_material: str


@router.get("/{sprint_id}", response_model=SprintMaterialResponse)
async def get_or_generate_material(
    sprint_id: int, 
    db: AsyncSession = Depends(get_db)
):
    """
    **Get Detailed Sprint Study Material**

    Fetches the 1-2 pages of comprehensive study notes for a specific sprint.
    If it hasn't been generated yet, it dynamically creates it using the sprint's
    topic, the sprint's bullet points, and the student's original uploaded
    notes/syllabus context. Generates cached markdown.
    """
    # 1. Load the sprint and eager load the hierarchy to get context
    result = await db.execute(
        select(SprintSessionRecord)
        .options(
            selectinload(SprintSessionRecord.study_plan)
            .selectinload(StudyPlanRecord.session)
        )
        .where(SprintSessionRecord.id == sprint_id)
    )
    sprint = result.scalar_one_or_none()
    
    if not sprint:
        raise HTTPException(status_code=404, detail=f"Sprint {sprint_id} not found.")

    # 2. Check if we already generated it
    if sprint.detailed_material:
        return SprintMaterialResponse(
            sprint_id=sprint.id,
            topic=sprint.topic,
            detailed_material=sprint.detailed_material
        )

    # 3. We assume study_plan and session exist because of DB constraints
    session_rec: SessionRecord = sprint.study_plan.session
    notes_context = session_rec.notes_text or ""
    syllabus_context = session_rec.syllabus_text or ""
    content_bullets = sprint.get_content()

    # 4. Generate the material
    markdown = await _material_agent.generate_material(
        topic=sprint.topic,
        content_bullets=content_bullets,
        notes_context=notes_context,
        syllabus_context=syllabus_context,
    )

    # 5. Save back to DB
    sprint.detailed_material = markdown
    await db.commit()

    return SprintMaterialResponse(
        sprint_id=sprint.id,
        topic=sprint.topic,
        detailed_material=markdown
    )
