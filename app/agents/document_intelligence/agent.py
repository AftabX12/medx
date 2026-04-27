from __future__ import annotations

import dspy

from app.agents.document_intelligence.signatures import DocumentIntelligenceSig
from app.agents.state import DocumentUnderstanding


class DocumentIntelligenceAgent(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self.analyze = dspy.ChainOfThought(DocumentIntelligenceSig)

    def forward(self, ocr_text: str) -> DocumentUnderstanding:
        text = ocr_text[:10000]
        result = self.analyze(ocr_text=text)
        return DocumentUnderstanding(
            document_nature=result.document_nature or "",
            clinical_domain=result.clinical_domain or "",
            observation_date=result.observation_date,
            patient_identifiers=result.patient_identifiers or {},
            provider_info=result.provider_info or {},
            clinical_findings=result.clinical_findings or [],
            medications=result.medications or [],
            problems=result.problems or [],
            allergies=result.allergies or [],
            notable=result.notable or "",
        )
