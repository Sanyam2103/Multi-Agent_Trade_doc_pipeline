# pyrefly: ignore [missing-import]
import aiosqlite
import os
from typing import Dict, Any

DB_PATH = "analytics.sqlite"

async def initialize_analytics_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS shipments (
                document_id TEXT PRIMARY KEY,
                document_type TEXT,
                final_status TEXT,
                agent_reasoning TEXT,
                drafted_email TEXT,
                average_confidence REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                consignee_name TEXT, consignee_name_confidence REAL,
                hs_code TEXT, hs_code_confidence REAL,
                port_of_loading TEXT, port_of_loading_confidence REAL,
                port_of_discharge TEXT, port_of_discharge_confidence REAL,
                incoterms TEXT, incoterms_confidence REAL,
                description_of_goods TEXT, description_of_goods_confidence REAL,
                gross_weight TEXT, gross_weight_confidence REAL,
                invoice_number TEXT, invoice_number_confidence REAL
            )
        ''')
        await db.commit()

async def save_shipment_to_analytics(state: dict):
    extracted_data = state.get("extracted_data") or {}
    
    def get_val(field):
        f = extracted_data.get(field)
        if isinstance(f, dict):
            return f.get("value"), f.get("confidence")
        return f, None
        
    consignee_name, consignee_name_conf = get_val("consignee_name")
    hs_code, hs_code_conf = get_val("hs_code")
    port_of_loading, port_of_loading_conf = get_val("port_of_loading")
    port_of_discharge, port_of_discharge_conf = get_val("port_of_discharge")
    incoterms, incoterms_conf = get_val("incoterms")
    description_of_goods, description_of_goods_conf = get_val("description_of_goods")
    gross_weight, gross_weight_conf = get_val("gross_weight")
    invoice_number, invoice_number_conf = get_val("invoice_number")
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            INSERT OR REPLACE INTO shipments (
                document_id, document_type, final_status, agent_reasoning, drafted_email,
                average_confidence, consignee_name, consignee_name_confidence,
                hs_code, hs_code_confidence, port_of_loading, port_of_loading_confidence,
                port_of_discharge, port_of_discharge_confidence, incoterms, incoterms_confidence,
                description_of_goods, description_of_goods_confidence, gross_weight, gross_weight_confidence,
                invoice_number, invoice_number_confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            state.get("document_id"),
            state.get("document_type"),
            state.get("final_status"),
            state.get("agent_reasoning"),
            state.get("drafted_email"),
            state.get("current_confidence"),
            consignee_name, consignee_name_conf,
            hs_code, hs_code_conf,
            port_of_loading, port_of_loading_conf,
            port_of_discharge, port_of_discharge_conf,
            incoterms, incoterms_conf,
            description_of_goods, description_of_goods_conf,
            gross_weight, gross_weight_conf,
            invoice_number, invoice_number_conf
        ))
        await db.commit()
