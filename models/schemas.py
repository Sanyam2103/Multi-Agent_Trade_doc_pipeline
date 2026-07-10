# pyrefly: ignore [missing-import]
from pydantic import BaseModel, Field
from typing import Type, Union, Literal, Optional

class ExtractedField(BaseModel):
    value: str
    confidence: float = Field(..., ge=0.0, le=1.0, description="The LLM's confidence for this specific field (0.0 to 1.0).")

class ExtractedNumberField(BaseModel):
    value: float
    confidence: float = Field(..., ge=0.0, le=1.0, description="The LLM's confidence for this specific field (0.0 to 1.0).")

class CommercialInvoiceSchema(BaseModel):
    """Data model for a Commercial Invoice."""
    invoice_number: ExtractedField = Field(..., description="The unique identifier for the invoice.")
    consignee_name: ExtractedField = Field(..., description="The name of the consignee or recipient.")
    hs_code: ExtractedField = Field(..., description="The Harmonized System code for the goods.")
    incoterms: ExtractedField = Field(..., description="The Incoterms rule for the shipment (e.g., FOB, CIF).")
    description_of_goods: ExtractedField = Field(..., description="A description of the items in the shipment.")
    gross_weight: ExtractedField = Field(..., description="The total weight of the goods, including packaging.")
    total_amount: ExtractedNumberField = Field(..., description="The total monetary value of the invoice.")

class BillOfLadingSchema(BaseModel):
    """Data model for a Bill of Lading."""
    bol_number: ExtractedField = Field(..., description="The unique Bill of Lading number.")
    shipper_name: ExtractedField = Field(..., description="The name of the shipper or party sending the goods.")
    consignee_name: ExtractedField = Field(..., description="The name of the consignee or recipient.")
    port_of_loading: ExtractedField = Field(..., description="The port where the cargo is loaded.")
    port_of_discharge: ExtractedField = Field(..., description="The port where the cargo will be unloaded.")
    description_of_goods: ExtractedField = Field(..., description="A description of the items in the shipment.")
    gross_weight: ExtractedField = Field(..., description="The total weight of the goods, including packaging.")
    total_package_count: ExtractedField = Field(..., description="The total number of individual packages in the shipment.")
    container_number: ExtractedField = Field(..., description="The unique identifier for the shipping container.")

class PackingListSchema(BaseModel):
    """Data model for a Packing List."""
    exporter_name: ExtractedField = Field(..., description="The name of the party exporting the goods.")
    consignee_name: ExtractedField = Field(..., description="The name of the party receiving the goods.")
    invoice_number: ExtractedField = Field(..., description="The invoice number associated with this packing list.")
    hs_code: Optional[ExtractedField] = Field(None, description="The Harmonized System code for the goods, if available.")
    total_gross_weight: ExtractedField = Field(..., description="The total weight of all packages in the shipment.")
    total_volume: Optional[ExtractedField] = Field(None, description="The total cubic volume of the shipment, if available.")
    total_package_count: ExtractedField = Field(..., description="The total number of individual packages in the shipment.")


# A map to easily retrieve the schema class from a string
SCHEMA_MAP = {
    "COMMERCIAL_INVOICE": CommercialInvoiceSchema,
    "BILL_OF_LADING": BillOfLadingSchema,
    "PACKING_LIST": PackingListSchema,
}

def get_schema_for_doc(doc_type: str) -> Union[Type[CommercialInvoiceSchema], Type[BillOfLadingSchema], Type[PackingListSchema]]:
    """
    Returns the Pydantic schema class corresponding to the given document type.

    Args:
        doc_type: The type of the document (e.g., 'COMMERCIAL_INVOICE').

    Returns:
        The corresponding Pydantic BaseModel class.
        
    Raises:
        ValueError: If the document type is unknown.
    """
    schema = SCHEMA_MAP.get(doc_type.upper())
    if not schema:
        raise ValueError(f"Unknown document type: '{doc_type}'. No schema available.")
    return schema
