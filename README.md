# Multi-Agent Trade Document Pipeline

A full-stack, asynchronous multi-agent orchestration pipeline designed to automate the extraction, validation, and analytics of complex logistics and trade documents (like Commercial Invoices and Bills of Lading).

This application leverages **FastAPI** for the backend, **LangGraph** for multi-agent workflow orchestration, **Claude 4.6 Sonnet / 4.5 Haiku** for intelligent data extraction and reasoning, and a clean **Vanilla JS + Tailwind CSS** frontend for end-users. It also features a built-in **Natural Language to SQL (Text-to-SQL)** AI Data Analyst to query processed shipments dynamically.

## 🌟 Key Features

- **Intelligent Classification & Extraction**: Automatically identifies document types and extracts mandatory logistics fields using a tiered extraction approach (Vision-Language Models + AWS Textract).
- **Granular Confidence Scoring**: Provides field-level confidence scores instead of just a global document score.
- **Strict Business Validation**: An automated reconciliation engine audits extracted fields against expected customer contract rules, utilizing smart shorthand/substring guards and confidence-split gates to prevent false mismatch penalties.
- **Automated Remediation**: If a document requires human review or an amendment, the agent explicitly documents its technical reasoning and drafts a highly professional email to the supplier detailing the exact discrepancies.
- **Natural Language Data Analytics**: Processed documents are safely archived into a local relational SQLite database (`analytics.sqlite`). The frontend features an "Ask the Data Analyst" section where users can query their shipments using natural language (powered by Claude 4.5 Haiku acting as a Text-to-SQL engine).
- **Responsive UI**: A beautiful, glassmorphic single-page dashboard with drag-and-drop uploads, execution summaries, and a detailed Audit & Validation Matrix.

---

## 🏗️ Architecture Stack

- **Backend**: Python, FastAPI, Pydantic
- **Multi-Agent Orchestration**: LangGraph, Anthropic API (Claude)
- **Database / State Persistence**: `aiosqlite` (SQLite)
- **Frontend**: HTML5, Vanilla JavaScript, Tailwind CSS (via CDN)

---

## 🚀 Getting Started

### Prerequisites

1. **Python 3.10+** installed on your system.
2. An active **Anthropic API Key** (for Claude models).

### Installation

1. **Clone or navigate** to the project directory.
2. **Create a virtual environment** (recommended):
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   ```
3. **Install Dependencies**:
   Ensure you have the required packages installed:
   ```bash
   pip install fastapi uvicorn pydantic python-dotenv aiofiles aiosqlite langgraph anthropic
   ```
4. **Environment Variables**:
   Create a `.env` file in the root directory and add your API key:
   ```env
   ANTHROPIC_API_KEY=your_anthropic_api_key_here
   ```

---

## 💻 Running the Application

The application requires two servers running simultaneously: one for the FastAPI backend and one to serve the static frontend HTML.

### 1. Start the FastAPI Backend
Open a terminal, activate your virtual environment, and run:
```bash
uvicorn api.main:app --reload
```
*The backend will boot up, initialize the analytics database, compile the LangGraph app, and listen on `http://127.0.0.1:8000`.*

### 2. Start the Frontend Server
Open a second terminal, navigate to the project directory, and start a simple Python HTTP server to serve `index.html`:
```bash
python -m http.server 8080
```

### 3. Access the Dashboard
Open your web browser and navigate to:
**`http://localhost:8080`**

From here, you can drag and drop a trade document (image/PDF) to see the multi-agent pipeline in action!

---

## 🌐 API Endpoints

- `POST /process-document`: Accepts a multipart/form-data `file` upload. Triggers the LangGraph asynchronous execution, evaluates the document, saves the results to the local analytics DB, and returns the audit results.
- `POST /query`: The Natural Language Query endpoint. Accepts JSON `{"question": "string"}`. Generates raw SQL using Claude, queries the SQLite DB, and synthesizes a natural language answer.

---

## 📁 Project Structure

```text
├── api/
│   └── main.py              # FastAPI application, API endpoints, lifespan DB init
├── agents/
│   ├── graph.py             # LangGraph workflow definition and state routing
│   └── nodes.py             # Individual agent node logic (extractor, validator, router)
├── models/
│   ├── schemas.py           # Pydantic schemas defining the expected extracted fields
│   └── state.py             # Defines the LangGraph DocumentState dictionary
├── utils/
│   ├── business_rules.py    # Strict auditing engine logic and customer profiles
│   └── storage.py           # Async SQLite database layer for analytics archiving
├── index.html               # The frontend dashboard UI
├── .env                     # Environment variables (API Keys)
├── requirements.txt         # (Optional) Python dependencies
├── analytics.sqlite         # Automatically generated db storing processed shipments
└── checkpoints.sqlite       # Automatically generated db for LangGraph state persistence
```
