
import os
import uuid
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
import aiofiles
# pyrefly: ignore [missing-import]
from fastapi import FastAPI, UploadFile, File, HTTPException,status
# pyrefly: ignore [missing-import]
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
# pyrefly: ignore [missing-import]
from fastapi.responses import JSONResponse
# pyrefly: ignore [missing-import]
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

# pyrefly: ignore [missing-import]
from pydantic import BaseModel
# pyrefly: ignore [missing-import]
import anthropic
# pyrefly: ignore [missing-import]
import aiosqlite

from models.state import DocumentState
from agents.graph import workflow # Import the raw workflow builder
from utils.storage import initialize_analytics_db, save_shipment_to_analytics, DB_PATH


# Load environment variables from .env file
load_dotenv()

# Define a directory to store uploaded files
UPLOADS_DIR = "uploads"
os.makedirs(UPLOADS_DIR, exist_ok=True)

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
        yield # The application runs while in this yielded state
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

@app.post("/process-document")
async def process_document(file: UploadFile = File(...)):
    """
    Accepts a document, saves it locally, and kicks off the asynchronous
    LangGraph processing pipeline.
    """
    try:
        thread_id = uuid.uuid4()
        file_id = str(thread_id)
        
        # Sanitize filename and create a unique path
        sanitized_filename = "".join(c for c in file.filename if c.isalnum() or c in ['.', '_', '-']).strip()
        file_location = os.path.join(UPLOADS_DIR, f"{file_id}_{sanitized_filename}")
        
        # Asynchronously save the uploaded file
        async with aiofiles.open(file_location, 'wb') as out_file:
            content = await file.read()
            await out_file.write(content)
            
        print(f"File '{file.filename}' uploaded and saved to '{file_location}'")

        # Initialize the state for the graph
        initial_state = DocumentState(
            document_id=file_id,
            document_path=os.path.abspath(file_location),
            document_type=None,
            extraction_tier=1,
            current_confidence=0.0,
            raw_text_fallback=None,
            extracted_data=None,
            validation_report=None,
            final_status="processing",
            drafted_email=None
        )
        
        # LangGraph config requires a string-based thread_id for persistence
        config = {"configurable": {"thread_id": str(thread_id)}}

        print(f"Invoking graph for thread_id: {thread_id}")
        
        # Asynchronously invoke the graph and wait for the final state
        final_state = await app.state.graph_app.ainvoke(initial_state, config)
        
        print(f"Graph execution finished. Final status: {final_state.get('final_status')}")
        
        # Save to relational analytics database
        await save_shipment_to_analytics(final_state)
        print("Shipment saved to analytics DB.")
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "message": "Document processing complete.",
                "document_id": file_id,
                "final_status": final_state.get("final_status"),
                "validation_report": final_state.get("validation_report"),
                "extracted_data": final_state.get("extracted_data"),
                "current_confidence": final_state.get("current_confidence"),
                "drafted_email": final_state.get("drafted_email"),
                "agent_reasoning": final_state.get("agent_reasoning"),
            }
        )

    except Exception as e:
        print(f"An error occurred during document processing: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": f"An internal server error occurred: {e}"}
        )

@app.get("/")
def read_root():
    return {"message": "Welcome to the Multi-Agent Trade Document Pipeline API"}

class QueryRequest(BaseModel):
    question: str

@app.post("/query")
async def query_analytics(request: QueryRequest):
    try:
        # Step 1: Text-to-SQL Generation
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        schema_ddl = """
        CREATE TABLE shipments (
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
        """
        sql_prompt = (
            f"You are a SQL expert. Translate the following user question into a valid SQLite query "
            f"for the `shipments` table. Schema:\n{schema_ddl}\n\n"
            f"CRITICAL MAPPING RULES:\n"
            f"- `final_status` can ONLY be one of these exact string values: 'VERIFIED', 'HUMAN_REVIEW', 'AMENDMENT_REQUIRED'. Map user terms like 'approved' or 'auto-approved' to 'VERIFIED', and 'flagged' or 'review' to 'HUMAN_REVIEW'.\n"
            f"- `document_type` is typically 'commercial_invoice' or 'bill_of_lading'.\n"
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
