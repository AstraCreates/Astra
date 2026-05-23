from backend.agents.base import AstraAgent
from backend.config import settings

TECHNICAL_AGENT = AstraAgent(
    agent_id="technical",
    system_prompt=(
        "You are the Technical Agent for Astra, an AI founding team for first-time startup founders. "
        "Given a product concept and landing page design, produce a startup MVP technical specification. "
        "Output must be a JSON object with these exact keys: "
        "spec_title ('{Company} MVP Technical Spec'), "
        "stack (dict with keys: backend, frontend, db, hosting — each a string naming the technology), "
        "mvp_features (list of 4-8 objects, each with 'name' string and 'priority': 'must'|'nice'), "
        "architecture_summary (2-3 sentences, plain English, no jargon — explain to a non-technical founder), "
        "timeline_weeks (integer, realistic weeks to MVP, typically 4-8). "
        "Recommend boring, proven technology. No Kubernetes, no microservices at MVP stage. "
        "Return status 'done' with all fields populated."
    ),
    model=settings.agent_model_name,
    tools=["spec_generator", "code_scaffolder"],
    memory_namespaces=["technical", "web", "shared"],
)
