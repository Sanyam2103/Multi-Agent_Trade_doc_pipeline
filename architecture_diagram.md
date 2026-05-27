# Multi-Agent Trade Document Pipeline Architecture

This diagram illustrates the end-to-end data flow and component interaction within the Multi-Agent Trade Document Pipeline.

```mermaid
graph TD
    %% Frontend
    User([User]) --> UI[Vanilla JS Frontend]

    %% Main API Endpoints
    UI -- "Upload Document" --> API_Upload[FastAPI: /process-document]
    UI -- "Natural Language Question" --> API_Query[FastAPI: /query]

    %% Upload Flow & LangGraph Pipeline
    API_Upload --> Pipeline[LangGraph Pipeline]

    subgraph LangGraph Orchestration
        Pipeline --> NodeClass[Classifier Node]
        NodeClass -- "Identify Doc Type" --> ClaudeClass[Claude 4.6 Sonnet]
        ClaudeClass --> NodeExtract[Extractor Node]

        subgraph Extraction Routing
            NodeExtract -- "Tier 1/2: Prompt Claude" --> ClaudeExtract[Claude 4.6 Sonnet]
            NodeExtract -- "Tier 3: Fallback" --> TextractExtract[AWS Textract]
        end

        NodeExtract --> NodeValidate[Validator Node]
        
        NodeValidate -- "Audit vs Customer Rules" --> NodeRouter[Router Node]
        
        subgraph Decision Routing
            NodeRouter -- "Match / Auto-Approve" --> Status1[VERIFIED]
            NodeRouter -- "Low Confidence / Needs Review" --> Status2[HUMAN_REVIEW]
            NodeRouter -- "Mismatch / Draft Email" --> Status3[AMENDMENT_REQUIRED]
        end
    end

    %% State Persistence
    Pipeline <--> StateDB[(checkpoints.sqlite)]

    %% Analytics Storage
    Status1 --> AnalyticsStorage[Save to Analytics]
    Status2 --> AnalyticsStorage
    Status3 --> AnalyticsStorage
    AnalyticsStorage --> AnalyticsDB[(analytics.sqlite)]

    %% Query Flow
    API_Query --> T2S[Text-to-SQL Prompt]
    T2S --> ClaudeQuery[Claude 4.5 Haiku]
    ClaudeQuery -- "Raw SQL Query" --> AnalyticsDB
    AnalyticsDB -- "Raw Query Results" --> AnswerSynth[Answer Synthesis Prompt]
    AnswerSynth --> ClaudeQuery
    ClaudeQuery -- "Synthesized Answer" --> API_Query
    API_Query --> UI
```

### Flow Breakdown:
1. **Document Processing**: A user uploads a document via the frontend. FastAPI receives it and kicks off the LangGraph pipeline. The document is classified and then extracted using Claude (or AWS Textract as a fallback). The data is validated against strict business rules, and a final decision is routed (Approve, Review, or Amend). The final state is stored in `analytics.sqlite`.
2. **Analytics Querying**: A user asks a natural language question. The backend prompts Claude 4.5 Haiku with the database schema to generate a SQL query. The query runs against `analytics.sqlite`, and the raw results are passed back to Claude to synthesize a final human-readable answer.
