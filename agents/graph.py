# pyrefly: ignore [missing-import]
from langgraph.graph import StateGraph, END
from models.state import ShipmentState
from agents.nodes import extractor_node, validator_node, router_node

def route_after_extraction(state: ShipmentState) -> str:
    """
    Determines the next step after the extraction node.
    - If any slot has low confidence and has retries left, re-run extraction.
    """
    needs_retry = False
    
    for slot_key in ["commercial_invoice", "bill_of_lading", "packing_list"]:
        slot = state.get(slot_key)
        if slot:
            conf = slot.get("current_confidence", 0.0)
            tier = slot.get("extraction_tier", 1)
            if conf < 0.7 and tier < 4:
                needs_retry = True
                print(f"Slot {slot_key} needs retry. (Confidence: {conf}, Tier: {tier})")

    if needs_retry:
        print("Decision: Retries available for one or more documents. Looping back to extractor.")
        return "extractor_node"
    else:
        print("Decision: All documents extracted or retries exhausted. Proceeding to validator.")
        return "validator_node"

# This file purely defines the graph structure and returns the workflow object.
# The compilation with a checkpointer is now handled asynchronously in the
# FastAPI server layer using the `lifespan` context manager.

# Initialize the graph
workflow = StateGraph(ShipmentState)

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
