from typing import TypedDict, Optional, Dict, Any, List

class DocumentSlot(TypedDict):
    """Holds the granular processing state for one specific document."""
    document_id: str               # The unique UUID for this specific file
    document_path: str             # Where the file lives on disk
    document_type: str             # E.g., 'commercial_invoice'
    
    # --- Processing Metrics ---
    extraction_tier: int           # Tracks retries specifically for THIS file
    current_confidence: float      # The average confidence score for THIS file
    raw_text_fallback: Optional[str] 
    
    # --- The Payload ---
    extracted_data: Optional[Dict[str, Any]] # The JSON payload (e.g., the invoice data)

class ShipmentState(TypedDict):
    """The master state for the entire LangGraph thread (batch)."""
    batch_id: str                  # The folder name (e.g., 'email_001')
    unprocessed_files: List[str]   # Raw file paths waiting to be sorted into slots
    
    # --- The Document Slots ---
    commercial_invoice: Optional[DocumentSlot]
    bill_of_lading: Optional[DocumentSlot]
    packing_list: Optional[DocumentSlot]
    
    # --- Batch-Level Outcomes ---
    validation_report: Optional[Dict[str, Any]] 
    cross_validation_report: Optional[Dict[str, Any]] # For comparing slots
    
    final_status: str              # VERIFIED, HUMAN_REVIEW, AMENDMENT_REQUIRED
    agent_reasoning: Optional[str] 
    drafted_email: Optional[str]
