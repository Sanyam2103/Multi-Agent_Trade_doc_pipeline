# pyrefly: ignore [missing-import]
import aiosqlite
import os
from typing import Dict, Any

DB_PATH = "analytics.sqlite"

async def initialize_analytics_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS shipments (
                batch_id TEXT PRIMARY KEY,
                final_status TEXT,
                agent_reasoning TEXT,
                drafted_email TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS commercial_invoices (
                document_id TEXT PRIMARY KEY,
                batch_id TEXT,
                document_path TEXT,
                average_confidence REAL,
                invoice_number TEXT, invoice_number_confidence REAL,
                consignee_name TEXT, consignee_name_confidence REAL,
                hs_code TEXT, hs_code_confidence REAL,
                incoterms TEXT, incoterms_confidence REAL,
                description_of_goods TEXT, description_of_goods_confidence REAL,
                gross_weight TEXT, gross_weight_confidence REAL,
                total_amount REAL, total_amount_confidence REAL,
                FOREIGN KEY(batch_id) REFERENCES shipments(batch_id)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS bills_of_lading (
                document_id TEXT PRIMARY KEY,
                batch_id TEXT,
                document_path TEXT,
                average_confidence REAL,
                bol_number TEXT, bol_number_confidence REAL,
                shipper_name TEXT, shipper_name_confidence REAL,
                consignee_name TEXT, consignee_name_confidence REAL,
                port_of_loading TEXT, port_of_loading_confidence REAL,
                port_of_discharge TEXT, port_of_discharge_confidence REAL,
                description_of_goods TEXT, description_of_goods_confidence REAL,
                gross_weight TEXT, gross_weight_confidence REAL,
                total_package_count TEXT, total_package_count_confidence REAL,
                container_number TEXT, container_number_confidence REAL,
                FOREIGN KEY(batch_id) REFERENCES shipments(batch_id)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS packing_lists (
                document_id TEXT PRIMARY KEY,
                batch_id TEXT,
                document_path TEXT,
                average_confidence REAL,
                exporter_name TEXT, exporter_name_confidence REAL,
                consignee_name TEXT, consignee_name_confidence REAL,
                invoice_number TEXT, invoice_number_confidence REAL,
                hs_code TEXT, hs_code_confidence REAL,
                total_gross_weight TEXT, total_gross_weight_confidence REAL,
                total_volume TEXT, total_volume_confidence REAL,
                total_package_count TEXT, total_package_count_confidence REAL,
                FOREIGN KEY(batch_id) REFERENCES shipments(batch_id)
            )
        ''')
        await db.commit()

async def save_shipment_to_analytics(state: dict):
    batch_id = state.get("batch_id")
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Insert Master Shipment Record
        await db.execute('''
            INSERT OR REPLACE INTO shipments (
                batch_id, final_status, agent_reasoning, drafted_email
            ) VALUES (?, ?, ?, ?)
        ''', (
            batch_id,
            state.get("final_status"),
            state.get("agent_reasoning"),
            state.get("drafted_email")
        ))
        
        # Helper to extract value and confidence
        def get_val(extracted_data, field):
            f = extracted_data.get(field)
            if isinstance(f, dict):
                return f.get("value"), f.get("confidence")
            return f, None

        # Insert Commercial Invoice
        ci_slot = state.get("commercial_invoice")
        if ci_slot and ci_slot.get("extracted_data"):
            data = ci_slot["extracted_data"]
            await db.execute('''
                INSERT OR REPLACE INTO commercial_invoices (
                    document_id, batch_id, document_path, average_confidence,
                    invoice_number, invoice_number_confidence, consignee_name, consignee_name_confidence,
                    hs_code, hs_code_confidence, incoterms, incoterms_confidence,
                    description_of_goods, description_of_goods_confidence, gross_weight, gross_weight_confidence,
                    total_amount, total_amount_confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                ci_slot.get("document_id"), batch_id, ci_slot.get("document_path"), ci_slot.get("current_confidence"),
                *get_val(data, "invoice_number"), *get_val(data, "consignee_name"),
                *get_val(data, "hs_code"), *get_val(data, "incoterms"),
                *get_val(data, "description_of_goods"), *get_val(data, "gross_weight"),
                *get_val(data, "total_amount")
            ))
            
        # Insert Bill of Lading
        bol_slot = state.get("bill_of_lading")
        if bol_slot and bol_slot.get("extracted_data"):
            data = bol_slot["extracted_data"]
            await db.execute('''
                INSERT OR REPLACE INTO bills_of_lading (
                    document_id, batch_id, document_path, average_confidence,
                    bol_number, bol_number_confidence, shipper_name, shipper_name_confidence,
                    consignee_name, consignee_name_confidence, port_of_loading, port_of_loading_confidence,
                    port_of_discharge, port_of_discharge_confidence, description_of_goods, description_of_goods_confidence,
                    gross_weight, gross_weight_confidence, total_package_count, total_package_count_confidence,
                    container_number, container_number_confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                bol_slot.get("document_id"), batch_id, bol_slot.get("document_path"), bol_slot.get("current_confidence"),
                *get_val(data, "bol_number"), *get_val(data, "shipper_name"),
                *get_val(data, "consignee_name"), *get_val(data, "port_of_loading"),
                *get_val(data, "port_of_discharge"), *get_val(data, "description_of_goods"),
                *get_val(data, "gross_weight"), *get_val(data, "total_package_count"),
                *get_val(data, "container_number")
            ))

        # Insert Packing List
        pl_slot = state.get("packing_list")
        if pl_slot and pl_slot.get("extracted_data"):
            data = pl_slot["extracted_data"]
            await db.execute('''
                INSERT OR REPLACE INTO packing_lists (
                    document_id, batch_id, document_path, average_confidence,
                    exporter_name, exporter_name_confidence, consignee_name, consignee_name_confidence,
                    invoice_number, invoice_number_confidence, hs_code, hs_code_confidence,
                    total_gross_weight, total_gross_weight_confidence, total_volume, total_volume_confidence,
                    total_package_count, total_package_count_confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                pl_slot.get("document_id"), batch_id, pl_slot.get("document_path"), pl_slot.get("current_confidence"),
                *get_val(data, "exporter_name"), *get_val(data, "consignee_name"),
                *get_val(data, "invoice_number"), *get_val(data, "hs_code"),
                *get_val(data, "total_gross_weight"), *get_val(data, "total_volume"),
                *get_val(data, "total_package_count")
            ))

        await db.commit()
