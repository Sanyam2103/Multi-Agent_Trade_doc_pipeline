"""
This module contains the core business logic for the document processing pipeline.

It defines the reconciliation engine responsible for auditing extracted data against
customer-specific rules, ensuring that all mandatory fields meet the required
standards before proceeding to the next stage.
"""

from typing import Dict, Any

# Pyrefly Info: C2_Pyrefly_Tool_Created


import re

def normalize_text(text: Any) -> str:
    if not text:
        return ""
    text = str(text).lower().strip()
    
    # Replace superscripts to standard numbers so m³ becomes m3
    text = text.replace("³", "3").replace("²", "2")
    
    # Remove commas which are often used in numeric values
    text = text.replace(",", "")
    
    # Strip common units from the text to allow pure numeric comparison
    # Matches words like kg, kgs, kilo, kilos, m, m3, cm, mm, lbs, lb, oz, pallet, pallets
    text = re.sub(r'\b(kgs?|kilos?|lbs?|oz|m3?|c?mm?|pallets?)\b', '', text)
    
    # Remove any trailing .0 or .00 (e.g., 19860.00 -> 19860)
    text = re.sub(r'\.0+$', '', text)
    
    # Remove any extra characters that might be left hanging like dots or extra spaces
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def audit_extracted_fields(extracted_data: Dict[str, Any], expected_rules: Dict[str, str]) -> Dict[str, Any]:
    """
    Audits extracted document fields against a set of expected customer rules.

    This function serves as the core of the Contract Reconciliation Engine. It
    iterates through each field defined in the expected_rules, normalizes both
    the extracted value and the expected value, and categorizes the match
    quality.

    The reconciliation logic is as follows:
    1.  **Match**: The normalized extracted value is identical to the normalized
        expected value.
    2.  **Mismatch**: The field is missing from the extracted data or the
        normalized values are completely distinct.
    3.  **Uncertain**: The normalized extracted value contains the normalized
        expected value as a substring, or vice versa, but they are not an
        exact match. This indicates a potential partial match that requires
        review.

    Args:
        extracted_data: A dictionary containing the data extracted from the
                        document.
        expected_rules: A dictionary of customer-specific baseline values.

    Returns:
        A dictionary containing the overall validation status (`is_valid`) and
        a detailed breakdown of the audit results for each field.
    """
    audit_results = {}
    is_valid = True

    for field, expected_value in expected_rules.items():
        extracted_field_obj = extracted_data.get(field)
        
        if isinstance(extracted_field_obj, dict):
            extracted_value = extracted_field_obj.get("value")
            extraction_confidence = extracted_field_obj.get("confidence", 0.0)
        else:
            extracted_value = None
            extraction_confidence = 0.0
            
        # Normalize both values for a consistent comparison
        norm_expected = normalize_text(expected_value)
        norm_extracted = normalize_text(extracted_value)

        result = {
            "status": "",
            "found": extracted_value,
            "expected": expected_value,
            "explanation": "",
            "confidence": extraction_confidence
        }

        
        if norm_extracted == norm_expected:
            # Rule 1: Exact Match
            result["status"] = "match"
            result["explanation"] = "Exact textual match."
        elif norm_extracted and norm_expected and (norm_expected in norm_extracted or norm_extracted in norm_expected):
            # Rule 2: Shorthand / Substring Guard
            result["status"] = "uncertain"
            result["explanation"] = "Shorthand or partial containment detected."
            is_valid = False
        elif extraction_confidence >= 0.85:
            # Rule 3: Confidence-Split Gate (High Confidence)
            result["status"] = "mismatch"
            result["explanation"] = "High-confidence extraction explicitly conflicts with contract rules."
            is_valid = False
        else:
            # Rule 3: Confidence-Split Gate (Low Confidence)
            result["status"] = "uncertain"
            result["explanation"] = "Text discrepancy accompanied by low VLM clarity score. Potential legibility issue."
            is_valid = False
            
        audit_results[field] = result

    return {"is_valid": is_valid, "audit_results": audit_results}
