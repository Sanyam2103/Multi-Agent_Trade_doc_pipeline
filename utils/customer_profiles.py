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
            "commercial_invoice": {
                "invoice_number": "34567",
                "consignee_name": "XYZ Imports",
                "hs_code": "3926.00.00",
                "incoterms": "FOB LONGBEACH",
                "description_of_goods": "BAR STOOL ALUMINIUM 500 X 100 X 100MM STAINLESS STEEL",
                "gross_weight": "225",
                "total_amount": "19860"
            },
            "bill_of_lading": {
                "bol_number": "LONSYD123456",
                "shipper_name": "ABC Exports",
                "consignee_name": "XYZ Imports",
                "port_of_loading": "Long Beach",
                "port_of_discharge": "Sydney",
                "description_of_goods": "20'GP CONTAINER",
                "gross_weight": "3,225",
                "total_package_count": "27",
                "container_number": "TTIU456789"
            },
            "packing_list": {
                "exporter_name": "ABC Exports",
                "consignee_name": "XYZ Imports",
                "invoice_number": "34567",
                "hs_code": "",
                "total_gross_weight": "3,225",
                "total_volume": "27",
                "total_package_count": "16"
            }
        }
    }
    return profiles.get(customer_id, {})
