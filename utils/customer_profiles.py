"""
This module provides customer-specific rule sets for document validation.

Each customer profile contains baseline strings that the reconciliation engine
uses to audit extracted data against expected values. This centralized
approach allows for easy management and scaling of validation rules.
"""

# Pyrefly Info: C2_Pyrefly_Tool_Created


def get_customer_rules(customer_id: str) -> dict:
    """
    Retrieves the validation rule set for a given customer ID.

    This function acts as a repository for customer-specific data rules.
    Based on the customer_id, it returns a dictionary of mandatory fields
    and their expected baseline values.

    Args:
        customer_id: The unique identifier for the customer.

    Returns:
        A dictionary containing the customer's validation rules.
        Returns an empty dictionary if the customer ID is not found.
    """
    profiles = {
        "GOCOMET_CUSTOMER_01": {
            "bol_number": "BKG98765432",
            "consignee_name": "SUNRISE TRADING CO., LTD.",
            "port_of_loading": "HAMBURG, GERMANY",
            "port_of_discharge": "SINGAPORE",
            "description_of_goods": "INDUSTRIAL ELECTRIC MOTORS (MODEL: EM-500)",
            "gross_weight": "4,850 KGS",
            "container_number": "STC-SIN-01/20"
        }
    }
    return profiles.get(customer_id, {})
