from adk import Agent
from typing import Optional
import pydantic

class RetentionAdvice(pydantic.BaseModel):
    action: str  # "Review", "Break", "Sleep", "Switch Topic"
    message: str
    target_topic: Optional[str] = None

class RetentionBoosterAgent:
    def __init__(self):
        self.agent = Agent(
            name="RetentionBooster",
            instructions="""
            You monitor the student's learning state.
            Functions:
            - Schedule a 2-minute review of a topic learned 30 mins ago.
            - If the student shows fatigue signals (slow responses, 'I'm tired'), suggest a 5-min break or a 'Quick Win' topic.
            - Ensure the student doesn't spend too long on a single hard topic.
            """,
        )

    def monitor_fatigue(self, performance_score: float) -> RetentionAdvice:
        if performance_score < 0.5:
            return RetentionAdvice(action="Break", message="Take 5! Your brain needs to settle.")
        return RetentionAdvice(action="Review", message="Quick check-in on Topic A.")

if __name__ == "__main__":
    r = RetentionBoosterAgent()
    print(f"Agent {r.agent.name} initialized.")
