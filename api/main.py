from typing import List
import os
import uuid
import asyncio
import shutil
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
import aiofiles
# pyrefly: ignore [missing-import]
from fastapi import FastAPI, UploadFile, File, HTTPException,status
# pyrefly: ignore [missing-import]
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
# pyrefly: ignore [missing-import]
from fastapi import Request
# pyrefly: ignore [missing-import]
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
import json
# pyrefly: ignore [missing-import]
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

# pyrefly: ignore [missing-import]
from pydantic import BaseModel
# pyrefly: ignore [missing-import]
import anthropic
# pyrefly: ignore [missing-import]
import aiosqlite

from models.state import ShipmentState
from agents.graph import workflow # Import the raw workflow builder
from utils.storage import initialize_analytics_db, save_shipment_to_analytics, DB_PATH


# Load environment variables from .env file
load_dotenv()

# Define directories to store uploaded and watched files
UPLOADS_DIR = "uploads"
INBOX_DIR = "inbox"
PROCESSED_DIR = "processed"
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(INBOX_DIR, exist_ok=True)
os.makedirs(PROCESSED_DIR, exist_ok=True)

from models.state import ShipmentState

# Global list to hold client queues for SSE
connected_clients = []

async def watch_inbox_folder(app: FastAPI):
    """
    Background task that watches the ./inbox folder for new subfolders (simulated emails).
    It processes the entire batch through the Single Thread Multi-Slot State graph.
    """
    print("--- Starting Inbox Watcher Task ---")
    while True:
        try:
            for item in os.listdir(INBOX_DIR):
                item_path = os.path.join(INBOX_DIR, item)
                
                # Treat each subfolder as a batch/email
                if os.path.isdir(item_path):
                    batch_id = item
                    print(f"\n--- Found new batch (batch_id: {batch_id}) in inbox ---")
                    
                    unprocessed = []
                    for file_name in os.listdir(item_path):
                        file_path = os.path.join(item_path, file_name)
                        if os.path.isfile(file_path):
                            unprocessed.append(os.path.abspath(file_path))
                    
                    if unprocessed:
                        initial_state = ShipmentState(
                            batch_id=batch_id,
                            unprocessed_files=unprocessed,
                            commercial_invoice=None,
                            bill_of_lading=None,
                            packing_list=None,
                            validation_report=None,
                            cross_validation_report=None,
                            final_status="processing",
                            agent_reasoning=None,
                            drafted_email=None
                        )
                        config = {"configurable": {"thread_id": batch_id}}
                        
                        print(f"Invoking graph for batch: {batch_id}")
                        
                        # Notify frontend that processing has started
                        start_event = {"type": "processing_started", "batch_id": batch_id}
                        for client_q in connected_clients:
                            await client_q.put(start_event)
                            
                        try:
                            # 5 minute timeout for processing an entire batch
                            final_state = await asyncio.wait_for(app.state.graph_app.ainvoke(initial_state, config), timeout=300.0)
                            print(f"Graph execution finished for batch {batch_id}. Final status: {final_state.get('final_status')}")
                            await save_shipment_to_analytics(final_state)
                            print(f"Shipment details for batch {batch_id} saved to analytics DB.")
                            
                            # Notify frontend that processing is complete
                            result_event = {
                                "type": "processing_complete",
                                "message": "Document processing complete.",
                                "document_id": batch_id,
                                "final_status": final_state.get("final_status"),
                                "validation_report": final_state.get("validation_report"),
                                "cross_validation_report": final_state.get("cross_validation_report"),
                                "drafted_email": final_state.get("drafted_email"),
                                "agent_reasoning": final_state.get("agent_reasoning"),
                            }
                            for client_q in connected_clients:
                                await client_q.put(result_event)
                                
                        except asyncio.TimeoutError:
                            print(f"Timeout: Graph execution took longer than 300 seconds for {batch_id}")
                    
                    # Cleanup: Move the entire subfolder to the processed directory
                    dest_path = os.path.join(PROCESSED_DIR, item)
                    if os.path.exists(dest_path):
                        shutil.rmtree(dest_path) # Remove if it already exists to overwrite
                    shutil.move(item_path, dest_path)
                    print(f"--- Moved {item_path} to {dest_path} ---")
                    
        except Exception as e:
            print(f"Error in inbox watcher: {e}")
            
        await asyncio.sleep(5)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Asynchronous context manager to handle application startup and shutdown logic.
    This is the recommended modern approach for managing resources like database
    connections.
    """
    print("--- Server starting up ---")
    await initialize_analytics_db()
    print("Analytics DB initialized.")
    # Initialize the asynchronous checkpointer
    async with AsyncSqliteSaver.from_conn_string("checkpoints.sqlite") as saver:
        # Compile the graph using the live, async checkpointer and attach it to the app state
        app.state.graph_app = workflow.compile(checkpointer=saver)
        print("Graph compiled asynchronously and attached to app state.")
        
        # Start the background watcher task
        watcher_task = asyncio.create_task(watch_inbox_folder(app))
        
        yield # The application runs while in this yielded state
        
        # Cleanup on shutdown
        watcher_task.cancel()
    print("--- Server shutting down ---")

# Initialize the FastAPI app with the lifespan manager
app = FastAPI(
    title="Multi-Agent Trade Document Pipeline",
    description="An asynchronous, multi-agent pipeline for processing trade documents.",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows your local HTML file to communicate with the API
    allow_credentials=True,
    allow_methods=["*"],  # Allows POST, GET, etc.
    allow_headers=["*"],
)

@app.post("/process-document", status_code=status.HTTP_202_ACCEPTED)
async def process_document_upload(files: List[UploadFile] = File(...)):
    """
    Accepts multiple document uploads, saves them to a unique sub-directory in the 'inbox',
    and returns immediately. The background watcher will pick them up for processing as a single batch.
    """
    try:
        # Create a unique batch ID and a corresponding directory in the inbox for this upload session
        batch_id = str(uuid.uuid4())
        batch_dir = os.path.join(INBOX_DIR, batch_id)
        os.makedirs(batch_dir, exist_ok=True)
        
        # Loop through all uploaded files and save them to the same batch directory
        for file in files:
            # Sanitize filename and create the destination path
            sanitized_filename = "".join(c for c in file.filename if c.isalnum() or c in ['.', '_', '-']).strip()
            file_location = os.path.join(batch_dir, sanitized_filename)
            
            # Asynchronously save the uploaded file to the new batch directory
            async with aiofiles.open(file_location, 'wb') as out_file:
                content = await file.read()
                await out_file.write(content)
            
            print(f"File '{file.filename}' uploaded to inbox as part of batch '{batch_id}'")
        
        return {
            "message": "File(s) upload accepted. Processing has started.",
            "batch_id": batch_id
        }

    except Exception as e:
        print(f"An error occurred during document upload: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": f"An internal server error occurred during upload: {e}"}
        )

@app.get("/", response_class=FileResponse)
def read_root():
    # Serve the main HTML file from the root directory
    return FileResponse("index.html")

@app.get("/events")
async def sse_events(request: Request):
    """
    Server-Sent Events endpoint to push real-time updates to the frontend.
    """
    queue = asyncio.Queue()
    connected_clients.append(queue)

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                data = await queue.get()
                yield f"data: {json.dumps(data)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if queue in connected_clients:
                connected_clients.remove(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

class QueryRequest(BaseModel):
    question: str

@app.post("/query")
async def query_analytics(request: QueryRequest):
    try:
        # Step 1: Text-to-SQL Generation
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        schema_ddl = """
        CREATE TABLE shipments (
            batch_id TEXT PRIMARY KEY,
            final_status TEXT,
            agent_reasoning TEXT,
            drafted_email TEXT,
            created_at TIMESTAMP
        );
        CREATE TABLE commercial_invoices (
            document_id TEXT PRIMARY KEY, batch_id TEXT, document_path TEXT, average_confidence REAL,
            invoice_number TEXT, invoice_number_confidence REAL, consignee_name TEXT, consignee_name_confidence REAL,
            hs_code TEXT, hs_code_confidence REAL, incoterms TEXT, incoterms_confidence REAL,
            description_of_goods TEXT, description_of_goods_confidence REAL, gross_weight TEXT, gross_weight_confidence REAL,
            total_amount REAL, total_amount_confidence REAL, FOREIGN KEY(batch_id) REFERENCES shipments(batch_id)
        );
        CREATE TABLE bills_of_lading (
            document_id TEXT PRIMARY KEY, batch_id TEXT, document_path TEXT, average_confidence REAL,
            bol_number TEXT, bol_number_confidence REAL, shipper_name TEXT, shipper_name_confidence REAL,
            consignee_name TEXT, consignee_name_confidence REAL, port_of_loading TEXT, port_of_loading_confidence REAL,
            port_of_discharge TEXT, port_of_discharge_confidence REAL, description_of_goods TEXT, description_of_goods_confidence REAL,
            gross_weight TEXT, gross_weight_confidence REAL, total_package_count TEXT, total_package_count_confidence REAL,
            container_number TEXT, container_number_confidence REAL, FOREIGN KEY(batch_id) REFERENCES shipments(batch_id)
        );
        CREATE TABLE packing_lists (
            document_id TEXT PRIMARY KEY, batch_id TEXT, document_path TEXT, average_confidence REAL,
            exporter_name TEXT, exporter_name_confidence REAL, consignee_name TEXT, consignee_name_confidence REAL,
            invoice_number TEXT, invoice_number_confidence REAL, hs_code TEXT, hs_code_confidence REAL,
            total_gross_weight TEXT, total_gross_weight_confidence REAL, total_volume TEXT, total_volume_confidence REAL,
            total_package_count TEXT, total_package_count_confidence REAL, FOREIGN KEY(batch_id) REFERENCES shipments(batch_id)
        );
        """
        sql_prompt = (
            f"You are a SQL expert. Translate the following user question into a valid SQLite query.\n"
            f"Here is the database schema:\n{schema_ddl}\n\n"
            f"CRITICAL MAPPING RULES:\n"
            f"- ONLY GENERATE `SELECT` QUERIES. You are strictly forbidden from generating `UPDATE`, `DELETE`, `DROP`, `INSERT`, or `ALTER` queries. If the user asks to modify data, return a SELECT query that safely returns nothing or answers a related read-only question.\n"
            f"- Use JOINs to connect the `shipments` table with `commercial_invoices`, `bills_of_lading`, and `packing_lists` on `batch_id` when necessary.\n"
            f"- `final_status` in `shipments` can ONLY be 'VERIFIED', 'HUMAN_REVIEW', or 'AMENDMENT_REQUIRED'.\n"
            f"- For all text column comparisons (like ports, names, or incoterms), ALWAYS use case-insensitive matching (e.g. `LOWER(port_of_loading) LIKE LOWER('%value%')`) to prevent case mismatch errors.\n\n"
            f"User question: {request.question}\n\n"
            f"Return ONLY the raw executable SQL string, completely stripped of markdown code blocks, backticks, or preamble text."
        )
        
        sql_response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=300,
            messages=[{"role": "user", "content": sql_prompt}]
        )
        raw_sql = sql_response.content[0].text.strip()
        
        # Clean markdown formatting if present
        if raw_sql.startswith("```sql"):
            raw_sql = raw_sql[6:]
        if raw_sql.startswith("```"):
            raw_sql = raw_sql[3:]
        if raw_sql.endswith("```"):
            raw_sql = raw_sql[:-3]
        raw_sql = raw_sql.strip()
            
        # Step 1.5: Security Guardrail against destructive queries
        forbidden_keywords = ["UPDATE", "DELETE", "DROP", "INSERT", "ALTER", "TRUNCATE", "REPLACE", "CREATE"]
        upper_sql = raw_sql.upper()
        if any(keyword in upper_sql for keyword in forbidden_keywords):
            raise ValueError(f"Security Policy Violation: Destructive operations are not allowed. Extracted SQL: {raw_sql}")
            
        # Step 2: Local DB Execution
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(raw_sql)
            rows = await cursor.fetchall()
            db_output = [dict(row) for row in rows]
            
        # Step 3: Answer Synthesis
        synthesis_prompt = (
            f"You are a friendly logistics assistant. Synthesize a grounded natural-language answer "
            f"based on the user's question and the raw database output.\n\n"
            f"User Question: {request.question}\n"
            f"Database Output: {db_output}\n\n"
            f"Provide only the synthesized answer without any filler or preamble."
        )
        synthesis_response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=300,
            messages=[{"role": "user", "content": synthesis_prompt}]
        )
        final_answer = synthesis_response.content[0].text.strip()
        
        return {
            "answer": final_answer,
            "raw_sql": raw_sql,
            "db_output": db_output
        }
    except Exception as e:
        print(f"Error executing query: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": "Failed to process query", "error": str(e)}
        )
