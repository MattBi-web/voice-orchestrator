"""The web agent-builder: a FastAPI backend (this package) + a React
frontend (../../../web/) for creating and editing the agent family through
a browser instead of hand-editing config/agents.yaml.

Nothing in the text core (orchestrator.py, routing/, tools/, memory.py)
changes to support this — this package only adds a second, SQLite-backed
way to read and write an agent family, built from the same `AgentSpec` /
`ToolBinding` shapes `agents/registry.py` already defines. See `db.py`'s
module docstring for the two-sources-of-truth trade-off this implies
(config/agents.yaml for the CLI, this database for the web UI), and
`app.py` for the actual routes.
"""
