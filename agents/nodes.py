# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
import base64
import json
import os
import uuid
import concurrent.futures
import re
from typing import Dict, Any, Union, List, Optional

# pyrefly: ignore [missing-import]
import anthropic
# pyrefly: ignore [missing-import]
from pydantic import ValidationError
# pyrefly: ignore [missing-import]
from pdf2image import convert_from_path

from models.state import ShipmentState, DocumentSlot
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
        '"BILL_OF_LADING", "COMMERCIAL_INVOICE", or "PACKING_LIST". Respond with ONLY the document type name as a '
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
        if "BILL_OF_LADING" in classification or "COMMERCIAL_INVOICE" in classification or "PACKING_LIST" in classification:
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
        temp_image_filename = f"temp_{uuid.uuid4().hex[:8]}_{os.path.basename(file_path)}.jpg"
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

def process_single_file(file_path: str, existing_slot: Optional[DocumentSlot] = None) -> DocumentSlot:
    """Processes a single document file, handling classification and extraction."""
    doc_id = existing_slot.get("document_id") if existing_slot else str(uuid.uuid4())
    doc_type = existing_slot.get("document_type") if existing_slot else None
    tier = existing_slot.get("extraction_tier", 1) if existing_slot else 1
    
    if not doc_type:
        try:
            doc_type = _call_claude_classifier(file_path)
        except Exception as e:
            print(f"FATAL: Classification failed: {e}")
            return {"document_id": doc_id, "document_path": file_path, "document_type": "ERROR", "extraction_tier": tier, "current_confidence": 0.0, "raw_text_fallback": str(e), "extracted_data": None}
            
    try:
        target_schema = get_schema_for_doc(doc_type)
    except ValueError as e:
        return {"document_id": doc_id, "document_path": file_path, "document_type": doc_type, "extraction_tier": tier, "current_confidence": 0.0, "raw_text_fallback": str(e), "extracted_data": None}

    print(f"Executing extraction tier {tier} for {doc_type}...")
    avg_conf = 0.0
    extracted_data = None
    try:
        raw_json = ""
        if tier == 1:
            raw_json = _call_claude_extractor(target_schema.model_json_schema(), file_path=file_path)
        elif tier == 2:
            image_path = convert_pdf_to_image(file_path)
            if image_path:
                cleaned_image_path = clean_image_with_opencv(image_path)
                if cleaned_image_path:
                    raw_json = _call_claude_extractor(target_schema.model_json_schema(), file_path=cleaned_image_path)
        elif tier == 3:
            with open(file_path, "rb") as f:
                doc_bytes = f.read()
            table_text = extract_tables_with_textract(doc_bytes)
            prompt = f"Extract data based on the document's content, paying special attention to the following tables:\n\n{table_text}"
            raw_json = _call_claude_extractor(target_schema.model_json_schema(), text_prompt=prompt, file_path=file_path)
        
        if not raw_json:
            raise ValueError("LLM response was empty.")

        extracted_data = json.loads(raw_json)
        target_schema.model_validate(extracted_data)
        
        confidences = []
        for key, field_obj in extracted_data.items():
            if isinstance(field_obj, dict) and "confidence" in field_obj:
                confidences.append(field_obj["confidence"])
        
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        print(f"Extraction successful for {doc_type}. Average confidence: {avg_conf:.2f}")
        print(f"Extracted Data for {doc_type}:\n{json.dumps(extracted_data, indent=2)}")

    except Exception as e:
        print(f"An error occurred during tier {tier} for {doc_type}: {e}")
        avg_conf = existing_slot.get("current_confidence", 0.4) - 0.1 if existing_slot else 0.0

    return {
        "document_id": doc_id,
        "document_path": file_path,
        "document_type": doc_type,
        "extraction_tier": tier + 1,
        "current_confidence": avg_conf,
        "raw_text_fallback": None,
        "extracted_data": extracted_data
    }

def extractor_node(state: ShipmentState) -> ShipmentState:
    """Orchestrates concurrent extraction for all files in the batch."""
    print("\n---EXTRACTOR NODE (MULTI-SLOT BARRIER)---")
    
    files_to_process = []
    
    # 1. New files from unprocessed_files
    unprocessed = state.get("unprocessed_files", [])
    for f in unprocessed:
        files_to_process.append((f, None))
    state["unprocessed_files"] = [] # Clear them since we are processing them
    
    # 2. Existing slots that need retry (confidence < 0.7 and tier < 4)
    for slot_key in ["commercial_invoice", "bill_of_lading", "packing_list"]:
        slot = state.get(slot_key)
        if slot and slot.get("current_confidence", 0.0) < 0.7 and slot.get("extraction_tier", 1) < 4:
            files_to_process.append((slot["document_path"], slot))
            
    if not files_to_process:
        print("No files to process or retry.")
        return state

    print(f"Starting concurrent extraction for {len(files_to_process)} files...")
    
    results = []
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(process_single_file, path, slot) for path, slot in files_to_process]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    # Sort results into slots based on document_type
    for res in results:
        doc_type = res["document_type"]
        if "COMMERCIAL_INVOICE" in doc_type:
            state["commercial_invoice"] = res
        elif "BILL_OF_LADING" in doc_type:
            state["bill_of_lading"] = res
        elif "PACKING_LIST" in doc_type:
            state["packing_list"] = res
        else:
            print(f"Warning: Could not sort file {res['document_path']} with type {doc_type}")
            
    return state

def extract_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    s = str(val)
    matches = re.findall(r"[-+]?\d*\.\d+|\d+", s)
    if matches:
        try:
            return float(matches[0])
        except ValueError:
            return None
    return None

def clean_str(val: Any) -> str:
    if val is None:
        return ""
    return str(val).lower().strip().replace(".", "").replace(",", "")

def validator_node(state: ShipmentState) -> ShipmentState:
    print("\n---VALIDATOR NODE (PROFILE & CROSS-VALIDATION)---")
    
    # --- 1. Customer Profile Validation ---
    customer_id = 'GOCOMET_CUSTOMER_01'
    expected_rules = get_customer_rules(customer_id)
    
    all_audit_results = {}
    profile_is_valid = True
    
    for slot_key in ["commercial_invoice", "bill_of_lading", "packing_list"]:
        slot = state.get(slot_key)
        if slot and slot.get("extracted_data"):
            doc_rules = expected_rules.get(slot_key, {})
            val_result = audit_extracted_fields(slot["extracted_data"], doc_rules)
            all_audit_results[slot_key] = val_result["audit_results"]
            if not val_result["is_valid"]:
                profile_is_valid = False
        elif slot:
            all_audit_results[slot_key] = {"error": "Extraction failed for this document."}
            profile_is_valid = False

    state["validation_report"] = {
        "is_valid": profile_is_valid,
        "audit_results": all_audit_results
    }
    
    print(f"Validation Report Results: {profile_is_valid}")
    print(f"Detailed Validation Report:\n{json.dumps(all_audit_results, indent=2)}")
        
    # --- 2. Cross Validation ---
    errors = []
    
    # Step 1: Safe Extraction & Existence Guardrails
    inv_slot = state.get("commercial_invoice") or {}
    pl_slot = state.get("packing_list") or {}
    bol_slot = state.get("bill_of_lading") or {}
    
    inv = inv_slot.get("extracted_data") or {}
    pl = pl_slot.get("extracted_data") or {}
    bol = bol_slot.get("extracted_data") or {}
    
    def get_val(doc_dict: dict, field: str):
        f = doc_dict.get(field)
        if isinstance(f, dict):
            return f.get("value")
        return f

    if not inv:
        errors.append("CRITICAL: Missing complete document payload for Commercial Invoice.")
    if not pl:
        errors.append("CRITICAL: Missing complete document payload for Packing List.")
    if not bol:
        errors.append("CRITICAL: Missing complete document payload for Bill of Lading.")
        
    if errors:
        state["cross_validation_errors"] = errors
        state["cross_validation_report"] = {"is_valid": False, "issues": errors}
        state["final_status"] = "AMENDMENT_REQUIRED"
        return state

    # Field retrieval
    inv_inv_no = get_val(inv, "invoice_number")
    pl_inv_no = get_val(pl, "invoice_number")
    
    inv_consignee = get_val(inv, "consignee_name")
    pl_consignee = get_val(pl, "consignee_name")
    bol_consignee = get_val(bol, "consignee_name")
    
    inv_exporter = get_val(inv, "exporter_name")
    pl_exporter = get_val(pl, "exporter_name")
    bol_shipper = get_val(bol, "shipper_name")
    
    pl_weight = get_val(pl, "total_gross_weight")
    bol_weight = get_val(bol, "gross_weight")
    
    pl_packages = get_val(pl, "total_package_count")
    bol_packages = get_val(bol, "total_package_count")
    
    inv_hs = get_val(inv, "hs_code")
    pl_hs = get_val(pl, "hs_code")

    # Step 2: Cross-Validation Rule Engine
    
    # Rule 1: Document Linkage
    if inv_inv_no is None: errors.append("MISSING FIELD: invoice_number was not found in Commercial Invoice.")
    if pl_inv_no is None: errors.append("MISSING FIELD: invoice_number was not found in Packing List.")
    if inv_inv_no and pl_inv_no and clean_str(inv_inv_no) != clean_str(pl_inv_no):
        errors.append("DOCUMENT LINKAGE MISMATCH: Invoice number varies between Invoice and Packing List.")

    # Rule 2 & 3: Entity Consistency
    if inv_consignee is None: errors.append("MISSING FIELD: consignee_name was not found in Commercial Invoice.")
    if pl_consignee is None: errors.append("MISSING FIELD: consignee_name was not found in Packing List.")
    if bol_consignee is None: errors.append("MISSING FIELD: consignee_name was not found in Bill of Lading.")
    
    c_inv_cons, c_pl_cons, c_bol_cons = clean_str(inv_consignee), clean_str(pl_consignee), clean_str(bol_consignee)
    if c_inv_cons and c_pl_cons and c_bol_cons:
        if not (c_inv_cons == c_pl_cons == c_bol_cons):
            errors.append("IDENTITY MISMATCH: The Consignee or Exporter name varies across the shipment documents.")

    c_inv_exp, c_pl_exp, c_bol_ship = clean_str(inv_exporter), clean_str(pl_exporter), clean_str(bol_shipper)
    exporters = [x for x in [c_inv_exp, c_pl_exp, c_bol_ship] if x]
    if exporters and len(set(exporters)) > 1:
        if "IDENTITY MISMATCH: The Consignee or Exporter name varies across the shipment documents." not in errors:
            errors.append("IDENTITY MISMATCH: The Consignee or Exporter name varies across the shipment documents.")

    # Rule 4 & 5: Physical Logistics
    if pl_weight is None: errors.append("MISSING FIELD: total_gross_weight was not found in Packing List.")
    if bol_weight is None: errors.append("MISSING FIELD: gross_weight was not found in Bill of Lading.")
    w_pl, w_bol = extract_float(pl_weight), extract_float(bol_weight)
    if w_pl is not None and w_bol is not None and w_pl != w_bol:
        errors.append("PHYSICAL MISMATCH: Declared weights or package counts do not match between the Packing List and Carrier BOL.")

    if pl_packages is None: errors.append("MISSING FIELD: total_package_count was not found in Packing List.")
    if bol_packages is None: errors.append("MISSING FIELD: total_package_count was not found in Bill of Lading.")
    p_pl, p_bol = extract_float(pl_packages), extract_float(bol_packages)
    if p_pl is not None and p_bol is not None and p_pl != p_bol:
        if "PHYSICAL MISMATCH: Declared weights or package counts do not match between the Packing List and Carrier BOL." not in errors:
            errors.append("PHYSICAL MISMATCH: Declared weights or package counts do not match between the Packing List and Carrier BOL.")

    # Rule 6: Regulatory Alignment
    if inv_hs is None: errors.append("MISSING FIELD: hs_code was not found in Commercial Invoice.")
    if pl_hs is None: errors.append("MISSING FIELD: hs_code was not found in Packing List.")
    if inv_hs and pl_hs:
        if str(inv_hs)[:6] != str(pl_hs)[:6]:
            errors.append("CUSTOMS MISMATCH: The first 6 digits of the HS classification codes do not align.")

    # Step 3: State Update & Routing
    if len(errors) > 0:
        state["cross_validation_errors"] = errors
        state["cross_validation_report"] = {"is_valid": False, "issues": errors}
        state["final_status"] = "AMENDMENT_REQUIRED"
    else:
        state["cross_validation_errors"] = []
        state["cross_validation_report"] = {"is_valid": True, "issues": []}
        state["final_status"] = "VERIFIED"

    return state

def router_node(state: ShipmentState) -> ShipmentState:
    print("\n---ROUTER NODE (BATCH LEVEL)---")
    
    val_report = state.get("validation_report", {})
    cross_val_report = state.get("cross_validation_report", {})
    
    mismatches = []
    uncertainties = []
    
    # Aggregate issues from profile validation
    for doc_type, results in val_report.get("audit_results", {}).items():
        if "error" in results:
            mismatches.append({"document": doc_type, "error": results["error"]})
            continue
            
        for field, result in results.items():
            if result.get("status") == "mismatch":
                mismatches.append({"document": doc_type, "field": field, **result})
            elif result.get("status") == "uncertain":
                uncertainties.append({"document": doc_type, "field": field, **result})
                
    # Add cross-validation issues
    for issue in cross_val_report.get("issues", []):
        mismatches.append({"document": "CROSS_VALIDATION", "error": issue})

    try:
        if not mismatches and not uncertainties:
            state["final_status"] = "VERIFIED"
            state["agent_reasoning"] = "Automated clearance: All documents match profile and pass cross-validation perfectly."
            state["drafted_email"] = None
            print("Batch Status VERIFIED.")
            
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
                model="claude-haiku-4-5",
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}]
            )
            state["agent_reasoning"] = response.content[0].text.strip()
            state["drafted_email"] = None
            print("Batch Status HUMAN_REVIEW.")
            
        # OUTCOME 3: Draft Amendment Request
        else:
            state["final_status"] = "AMENDMENT_REQUIRED"
            prompt = (
                "You are an expert logistics compliance agent. "
                "The following shipment batch completely mismatched the expected contract or cross-validation rules:\n"
                f"{json.dumps(mismatches, indent=2)}\n\n"
                "You must return ONLY a raw JSON object (without markdown wrappers or code blocks) containing two keys:\n"
                "1. 'agent_reasoning': A sharp internal technical explanation summarizing the compliance failure.\n"
                "2. 'drafted_email': A highly professional, polite, itemized email addressed to the external supplier detailing each specific discrepancy and requesting an urgent, corrected document amendment."
            )
            response = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}]
            )
            raw_text = response.content[0].text.strip()
            
            # Clean up markdown formatting if present
            if raw_text.startswith("```json"):
                raw_text = raw_text[7:]
            elif raw_text.startswith("```"):
                raw_text = raw_text[3:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]
            
            raw_text = raw_text.strip()
            
            try:
                # Use strict=False to allow unescaped newlines which Claude often generates in long emails
                result_json = json.loads(raw_text, strict=False)
                state["agent_reasoning"] = result_json.get("agent_reasoning", "Failed to parse reasoning.")
                state["drafted_email"] = result_json.get("drafted_email", "Failed to parse email.")
            except json.JSONDecodeError as e:
                print(f"JSON Parse Error: {e}\nAttempting manual extraction from Claude's response.")
                # Fallback: if Claude failed to output valid JSON, just use the raw text as the email
                state["agent_reasoning"] = "System encountered mismatches. See drafted email for details."
                
                import re
                # Match anything after "drafted_email": " until the end, even if truncated
                email_match = re.search(r'"drafted_email"\s*:\s*"(.*)', raw_text, re.DOTALL)
                if email_match:
                    email_str = email_match.group(1)
                    # Remove trailing quote and bracket if they exist
                    if email_str.endswith('"}'): email_str = email_str[:-2]
                    elif email_str.endswith('"'): email_str = email_str[:-1]
                    state["drafted_email"] = email_str.replace('\\n', '\n')
                else:
                    state["drafted_email"] = raw_text
            print("Status set to AMENDMENT_REQUIRED. Amendment drafted.")

    except Exception as e:
        print(f"Error calling Anthropic API in router node: {e}")
        state["final_status"] = "HUMAN_REVIEW"
        state["agent_reasoning"] = f"Fallback state due to processing error: {str(e)}"
        
    print(f"\n--- Final Agent Reasoning ---\n{state.get('agent_reasoning', 'No reasoning generated.')}")    
    return state
