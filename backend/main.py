from fastapi import FastAPI
from agents.panic_intake import PanicIntakeAgent
from agents.prioritization import PrioritizationAgent
from agents.orchestrator import OrchestratorAgent
from agents.retention import RetentionBoosterAgent

app = FastAPI(title="Cramming Crisis Coordinator API")

# Initialize Agents
intake_agent = PanicIntakeAgent()
prioritizer = PrioritizationAgent()
orchestrator = OrchestratorAgent()
retention = RetentionBoosterAgent()

@app.get("/")
async def root():
    return {"message": "Swarm is ready to coordinate your panic."}

@app.post("/intake")
async def start_panic_session(data: dict):
    # Workflow integration will go here
    result = intake_agent.process_input(data.get("input", ""))
    return {"status": "success", "data": result}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
