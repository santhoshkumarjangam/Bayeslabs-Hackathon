from adk import Agent
from typing import List
import pydantic

class SprintSession(pydantic.BaseModel):
    topic: str
    duration_mins: int
    activity_type: str  # "Active Recall", "Flashcards", "Blurting"
    questions: List[str]

class OrchestratorAgent:
    def __init__(self):
        self.agent = Agent(
            name="Orchestrator",
            instructions="""
            You are the tactical lead. You take the prioritized topics and generate micro-sprints.
            Guidelines:
            - Each sprint is 5-15 minutes.
            - Focus on active recall: ask questions, don't just summarize.
            - If a student says 'I don't get X', break it down into a smaller sub-sprint immediately.
            """,
        )

    def create_sprint(self, topic: str) -> SprintSession:
        return SprintSession(
            topic=topic,
            duration_mins=15,
            activity_type="Active Recall",
            questions=["What is the primary function of...?", "How does X relate to Y?"]
        )

if __name__ == "__main__":
    o = OrchestratorAgent()
    print(f"Agent {o.agent.name} initialized.")
