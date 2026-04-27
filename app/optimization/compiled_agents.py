from __future__ import annotations

from pathlib import Path

from app.agents.chat.agent import ChatAgent
from app.agents.clinical_summary.agent import ClinicalSummaryAgent
from app.agents.data_steward.agent import PatientDataStewardAgent
from app.agents.document_intelligence.agent import DocumentIntelligenceAgent
from app.agents.registry import set_agents
from app.logging import get_logger

log = get_logger(__name__)


def load_compiled_agents():
    agents = {
        "document_intelligence": DocumentIntelligenceAgent(),
        "data_steward": PatientDataStewardAgent(),
        "clinical_summary": ClinicalSummaryAgent(),
        "chat": ChatAgent(),
    }
    for name, agent in agents.items():
        path = Path(f"app/optimization/compiled/{name}.json")
        if path.exists():
            agent.load(str(path))
            log.info("loaded_compiled_dspy_program", agent=name, path=str(path))
    set_agents(agents)
    return agents
