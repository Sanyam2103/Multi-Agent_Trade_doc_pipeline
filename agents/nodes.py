# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
import base64
import json
import os
from typing import Dict, Any, Union, List

# pyrefly: ignore [missing-import]
import anthropic
# pyrefly: ignore [missing-import]
from pydantic import ValidationError
# pyrefly: ignore [missing-import]
from pdf2image import convert_from_path

from models.state import DocumentState
from models.schemas import get_schema_for_doc
from utils.ocr_tools import clean_image_with_opencv, extract_tables_with_textract
from utils.file_handlers import convert_pdf_to_image
from utils.customer_profiles import get_customer_rules
from utils.business_rules import audit_extracted_fields

# Load environment variables from .env file
load_dotenv()


# --- Anthropic Client Initialization ---
try:
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
except ImportError:
    print("Anthropic SDK not installed. Please install with 'pip install anthropic'.")
    client = None
except Exception as e:
    print(f"Error initializing Anthropic client: {e}. Check API key.")
    client = None

def _call_claude_classifier(file_path: str) -> str:
    """
    Uses Claude 4.6 Sonnet to perform a fast classification of the document
    by sending only the first page.
    """
    print(f"---Classifying document: {os.path.basename(file_path)}---")
    if not client:
        raise ConnectionError("Anthropic client not initialized.")
    
    system_prompt = (
        'You are a document classifier. Your only task is to identify if the given document is a '
        '"BILL_OF_LADING" or a "COMMERCIAL_INVOICE". Respond with ONLY the document type name as a '
        'raw string, with no other text, conversation, or markdown formatting.'
    )
    
    encoded_data = ""
    media_type = ""

    if file_path.lower().endswith('.pdf'):
        try:
            images = convert_from_path(file_path, first_page=1, last_page=1)
            if images:
                import io
                buf = io.BytesIO()
                images[0].save(buf, format='JPEG')
                encoded_data = base64.b64encode(buf.getvalue()).decode('utf-8')
                media_type = "image/jpeg"
        except Exception as e:
            raise IOError(f"Failed to convert PDF first page for classification: {e}")
    else:
        with open(file_path, "rb") as f:
            encoded_data = base64.b64encode(f.read()).decode('utf-8')
        media_type = _get_media_type(file_path)

    if not encoded_data:
        raise ValueError("Could not extract first page for classification.")

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            system=system_prompt,
            max_tokens=50,
            messages=[{
                "role": "user",
                "content": [{
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": encoded_data},
                }],
            }],
        )
        classification = response.content[0].text.strip().replace('"', '')
        print(f"Claude classification result: '{classification}'")
        if "BILL_OF_LADING" in classification or "COMMERCIAL_INVOICE" in classification:
            return classification
        else:
            raise ValueError(f"Unexpected classification result: {classification}")
    except Exception as e:
        print(f"Error during classification API call: {e}")
        raise

def _get_media_type(file_path: str) -> str:
    """Determines the media type of a file based on its extension."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        return "application/pdf"
    elif ext in [".jpeg", ".jpg"]:
        return "image/jpeg"
    elif ext == ".png":
        return "image/png"
    else:
        # Fallback for other image types, though Claude might not support all
        return "application/octet-stream"

def _call_claude_extractor(
    schema: Dict[str, Any],
    file_path: str = None,
    text_prompt: str = None
) -> str:
    """
    Calls the Claude 4.6 Sonnet model with a document for data extraction.
    Can handle a raw file (PDF/image), a path to a cleaned image, or plain text.
    """
    if not client:
        raise ConnectionError("Anthropic client not initialized.")

    # --- Construct the prompt ---
    system_prompt = (
        "You are an expert logistics document processor. Your task is to accurately "
        "extract information from the provided document and return it as a valid JSON object "
        f"that strictly adheres to the following JSON schema: {json.dumps(schema)}. "
        "For each field, you must evaluate your legibility and certainty and populate the nested 'confidence' score (from 0.0 to 1.0)."
    )
    
    user_content: List[Dict[str, Any]] = []
    
    image_to_process_path = file_path
    
    # If the document is a PDF, convert its first page to a temporary image for extraction
    if file_path and file_path.lower().endswith('.pdf'):
        print("PDF detected. Converting first page to image for extraction...")
        # Create a temporary directory if it doesn't exist
        temp_dir = "temp_images"
        os.makedirs(temp_dir, exist_ok=True)
        
        # Define a path for the temporary image
        temp_image_filename = f"temp_{os.path.basename(file_path)}.jpg"
        image_to_process_path = os.path.join(temp_dir, temp_image_filename)

        try:
            # Convert PDF to image and save it
            temp_images = convert_from_path(file_path, first_page=1, last_page=1)
            if not temp_images:
                raise IOError("Failed to convert PDF to image for extraction.")
            temp_images[0].save(image_to_process_path, 'JPEG')
        except Exception as e:
            raise IOError(f"Error during PDF to image conversion: {e}")

    if image_to_process_path:
        media_type = _get_media_type(image_to_process_path)
        with open(image_to_process_path, "rb") as f:
            encoded_data = base64.b64encode(f.read()).decode('utf-8')
        user_content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": encoded_data},
        })

    if text_prompt:
        user_content.append({"type": "text", "text": text_prompt})

    if not user_content:
        raise ValueError("No content provided to send to Claude.")

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            system=system_prompt,
            max_tokens=2048,
            messages=[{"role": "user", "content": user_content}],
        )
        # Find the first JSON block in the response
        text_response = response.content[0].text
        json_part = text_response[text_response.find('{'):text_response.rfind('}')+1]
        return json_part
    except Exception as e:
        print(f"Error calling Claude API: {e}")
        raise
    finally:
        # Clean up the temporary image if it was created and is different from the original file_path
        if image_to_process_path != file_path and os.path.exists(image_to_process_path):
            os.remove(image_to_process_path)



def extractor_node(state: DocumentState) -> DocumentState:
    """The core agent for document classification and data extraction."""
    print("\n---EXTRACTOR & CLASSIFIER NODE---")
    
    doc_path = state.get("document_path")
    if not doc_path:
        state["final_status"] = "ERROR: Document path missing."
        return state

    if not state.get("document_type"):
        try:
            state["document_type"] = _call_claude_classifier(doc_path)
        except (ConnectionError, ValueError, IOError) as e:
            print(f"FATAL: Classification failed: {e}")
            state["final_status"] = "ERROR_CLASSIFICATION_FAILED"
            return state
            
    try:
        target_schema = get_schema_for_doc(state["document_type"])
    except ValueError as e:
        state["final_status"] = f"ERROR: {e}"
        return state

    tier = state.get("extraction_tier", 1)
    print(f"Executing extraction tier {tier}...")
    try:
        raw_json = ""
        if tier == 1:
            print("Tier 1: Direct extraction from native document.")
            raw_json = _call_claude_extractor(target_schema.model_json_schema(), file_path=doc_path)
        elif tier == 2:
            print("Tier 2: Lazy PDF conversion and image cleaning.")
            image_path = convert_pdf_to_image(doc_path)
            if image_path:
                cleaned_image_path = clean_image_with_opencv(image_path)
                if cleaned_image_path:
                    raw_json = _call_claude_extractor(target_schema.model_json_schema(), file_path=cleaned_image_path)
        elif tier == 3:
            print("Tier 3: Table extraction with Textract.")
            with open(doc_path, "rb") as f:
                doc_bytes = f.read()
            table_text = extract_tables_with_textract(doc_bytes)
            prompt = f"Extract data based on the document's content, paying special attention to the following tables:\n\n{table_text}"
            raw_json = _call_claude_extractor(target_schema.model_json_schema(), text_prompt=prompt, file_path=doc_path)
        
        if not raw_json:
            raise ValueError("LLM response was empty.")

        extracted_data = json.loads(raw_json)
        target_schema.model_validate(extracted_data)
        
        state["extracted_data"] = extracted_data
        
        # Calculate average confidence across all extracted fields
        confidences = []
        for key, field_obj in extracted_data.items():
            if isinstance(field_obj, dict) and "confidence" in field_obj:
                confidences.append(field_obj["confidence"])
        
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        state["current_confidence"] = avg_conf
        print(f"Extraction successful and validated. Average confidence: {avg_conf:.2f}")

    except (json.JSONDecodeError, ValidationError, ValueError, ConnectionError, IOError) as e:
        print(f"An error occurred during tier {tier}: {e}")
        state["current_confidence"] = state.get("current_confidence", 0.4) - 0.1
    
    state["extraction_tier"] += 1
    return state

def validator_node(state: DocumentState) -> DocumentState:
    """
    Validates the extracted data against customer-specific business rules.

    This node uses the Contract Reconciliation Engine to perform a strict,
    field-by-field audit of the extracted data against a customer's profile.
    It attaches a detailed validation report to the state.
    """
    print("\n---VALIDATOR NODE---")
    
    extracted_data = state.get("extracted_data")
    if extracted_data:
        print("Detailed Extracted Data & Confidence Scores:")
        print(json.dumps(extracted_data, indent=2))
        
    if not extracted_data:
        # If there's no data, create a validation report indicating the failure.
        state["validation_report"] = {
            "is_valid": False,
            "audit_results": {"error": "No data was extracted from the document."}
        }
        print("Validation failed: No data extracted.")
        return state

    # For testing, we assume a default customer context.
    # In a production scenario, this would be dynamically determined.
    customer_id = 'GOCOMET_CUSTOMER_01'
    expected_rules = get_customer_rules(customer_id)

    # Perform the audit using the core reconciliation engine
    validation_results = audit_extracted_fields(extracted_data, expected_rules)
    state['validation_report'] = validation_results
    
    print("\nDetailed Audit Report:")
    print(json.dumps(validation_results.get("audit_results", {}), indent=2))
    
    if not validation_results["is_valid"]:
        print("Validation failed. Detailed report generated.")
    else:
        print("Validation successful. All fields match the customer profile.")
        
    return state

def router_node(state: DocumentState) -> DocumentState:
    """Sets the final status and drafts an email or reasoning if review is needed."""
    print("\n---ROUTER NODE---")
    report = state.get("validation_report", {})
    audit_results = report.get("audit_results", {})
    
    mismatches = []
    uncertainties = []
    
    for field, result in audit_results.items():
        if result.get("status") == "mismatch":
            mismatches.append({"field": field, **result})
        elif result.get("status") == "uncertain":
            uncertainties.append({"field": field, **result})
            
    try:
        # OUTCOME 1: Auto-Approve
        if not mismatches and not uncertainties:
            state["final_status"] = "VERIFIED"
            state["agent_reasoning"] = "Automated clearance: All mandatory logistics fields match the authoritative customer contract profile exactly with 100% compliance."
            state["drafted_email"] = None
            print("Status set to VERIFIED. Data securely written to the primary relational warehouse.")
            
        # OUTCOME 2: Flag for Human Review
        elif not mismatches and uncertainties:
            state["final_status"] = "HUMAN_REVIEW"
            
            prompt = (
                "You are an expert logistics compliance agent. "
                "The following document fields had partial/fuzzy matches that need manual review:\n"
                f"{json.dumps(uncertainties, indent=2)}\n\n"
                "Write a concise, professional internal executive summary (1-2 sentences) "
                "explaining why a human supervisor needs to manually inspect this document "
                "(e.g., analyzing fuzzy matches or naming variations)."
            )
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}]
            )
            state["agent_reasoning"] = response.content[0].text.strip()
            state["drafted_email"] = None
            print("Status set to HUMAN_REVIEW. Reasoning generated.")
            
        # OUTCOME 3: Draft Amendment Request
        else:
            state["final_status"] = "AMENDMENT_REQUIRED"
            
            prompt = (
                "You are an expert logistics compliance agent. "
                "The following document fields completely mismatched the expected customer contract:\n"
                f"{json.dumps(mismatches, indent=2)}\n\n"
                "You must return ONLY a raw JSON object (without markdown wrappers or code blocks) containing two keys:\n"
                "1. 'agent_reasoning': A sharp internal technical explanation summarizing the compliance failure.\n"
                "2. 'drafted_email': A highly professional, polite, itemized email addressed to the external supplier detailing each specific discrepancy and requesting an urgent, corrected document amendment."
            )
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}]
            )
            
            try:
                # Attempt to parse the JSON response from Claude
                raw_text = response.content[0].text.strip()
                # Clean up if Claude included markdown
                if raw_text.startswith("```json"):
                    raw_text = raw_text[7:]
                if raw_text.startswith("```"):
                    raw_text = raw_text[3:]
                if raw_text.endswith("```"):
                    raw_text = raw_text[:-3]
                    
                result_json = json.loads(raw_text)
                state["agent_reasoning"] = result_json.get("agent_reasoning", "Failed to parse reasoning.")
                state["drafted_email"] = result_json.get("drafted_email", "Failed to parse email.")
            except json.JSONDecodeError:
                state["agent_reasoning"] = "System encountered mismatches but failed to generate structured reasoning."
                state["drafted_email"] = f"Mismatches detected: {json.dumps(mismatches)}"
                
            print("Status set to AMENDMENT_REQUIRED. Amendment drafted.")

    except Exception as e:
        print(f"Error calling Anthropic API in router node: {e}")
        state["final_status"] = "HUMAN_REVIEW"
        state["agent_reasoning"] = f"Fallback state due to processing error: {str(e)}"
        
    print(f"\n--- Final Agent Reasoning ---\n{state.get('agent_reasoning', 'No reasoning generated.')}")    
    return state
