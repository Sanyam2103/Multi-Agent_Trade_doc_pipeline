# pyrefly: ignore [missing-import]
from langgraph.graph import StateGraph, END
from models.state import DocumentState
from agents.nodes import extractor_node, validator_node, router_node

def route_after_extraction(state: DocumentState) -> str:
    """
    Determines the next step after the extraction node.
    - If confidence is high, proceed to validation.
    - If confidence is low but retries are left, re-run extraction.
    - If retries are exhausted, proceed to validation anyway.
    """
    confidence = state.get("current_confidence", 0.0)
    tier = state.get("extraction_tier", 1)

    print(f"---Routing after extraction (Confidence: {confidence}, Tier: {tier})---")

    if confidence >= 0.7:
        print("Decision: Confidence high. Proceeding to validator.")
        return "validator_node"
    elif tier < 4:
        print("Decision: Confidence low, retries available. Looping back to extractor.")
        return "extractor_node"
    else:
        print("Decision: Retries exhausted. Proceeding to validator.")
        return "validator_node"

# This file purely defines the graph structure and returns the workflow object.
# The compilation with a checkpointer is now handled asynchronously in the
# FastAPI server layer using the `lifespan` context manager.

# Initialize the graph
workflow = StateGraph(DocumentState)

# Add nodes to the graph
workflow.add_node("extractor_node", extractor_node)
workflow.add_node("validator_node", validator_node)
workflow.add_node("router_node", router_node)

# Set the entry point
workflow.set_entry_point("extractor_node")

# Add conditional edges from the extractor
workflow.add_conditional_edges(
    "extractor_node",
    route_after_extraction,
    {
        "validator_node": "validator_node",
        "extractor_node": "extractor_node",
    },
)

# Add the standard edge from validator to router
workflow.add_edge("validator_node", "router_node")

# The router node is the final step in this configuration
workflow.add_edge("router_node", END)

print("LangGraph workflow defined. Ready for async compilation.")
