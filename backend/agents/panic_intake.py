from adk import Agent, Schema
from typing import List, Optional
import pydantic

class PanicState(pydantic.BaseModel):
    panic_level: int = 5  # 1-10
    extracted_text: str = ""
    materials_count: int = 0
    urgency_reason: Optional[str] = None

class PanicIntakeAgent:
    def __init__(self):
        self.agent = Agent(
            name="PanicIntake",
            instructions="""
            You are the first point of contact for a stressed student. 
            Your goal is to:
            1. Calm the student down.
            2. Extract key information from their uploaded text/notes.
            3. Assess their panic level (1-10).
            4. Summarize what they have vs. what they need to know.
            Keep your responses supportive but extremely efficient.
            """,
        )

    def process_input(self, student_input: str) -> PanicState:
        # This will be replaced by actual ADK logic later
        # For now, we define the structure
        return PanicState(
            panic_level=8,
            extracted_text=student_input,
            materials_count=1,
            urgency_reason="Exam in 4 hours"
        )

if __name__ == "__main__":
    # Test stub
    intake = PanicIntakeAgent()
    print(f"Agent {intake.agent.name} initialized.")
