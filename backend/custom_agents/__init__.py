"""Custom agents — founder-defined specialists.

A custom agent is pure data: name + role prompt + a picked set of safe tools
+ model + optional recurring schedule. At run time it's turned into a normal
`backend.core.agent.Agent` and injected into the orchestrator alongside the
built-in specialists.
"""
