from typing import TypedDict, Optional, Dict, Any

class DocumentState(TypedDict):
    """
    Represents the state of a document as it moves through the processing pipeline.
    """
    document_id: str
    document_type: Optional[str]
    extraction_tier: int
    current_confidence: float
    raw_text_fallback: Optional[str]
    extracted_data: Optional[Dict[str, Any]]
    validation_report: Optional[Dict[str, Any]]
    final_status: str
    agent_reasoning: Optional[str]
    drafted_email: Optional[str]
    document_path: Optional[str] # New field for the file path
