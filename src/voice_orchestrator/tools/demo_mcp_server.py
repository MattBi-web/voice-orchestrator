"""A tiny MCP server bundled so the mcp_tool integration has something real
to talk to, with zero external setup (same spirit as FakeProvider — the
feature should be exercisable without any account, key, or network call).

NOT a real roaming/outage API — two toy tools over a small fake dataset,
just enough to prove the wiring: discovery, trigger scoring, and a real
stdio round-trip to an external process.

Run standalone: `python -m voice_orchestrator.tools.demo_mcp_server`
(config/mcp_servers.yaml's "demo" entry points mcp_tool.py's client at
exactly this command).
"""
from mcp.server.fastmcp import FastMCP

# Quiet by default — this is a backend tool call inside a voice turn, not a
# standalone service; its own request-logging noise shouldn't leak into the
# CLI's console output (same reasoning as the bm25s show_progress fix).
mcp = FastMCP("meridian-demo-tools", log_level="WARNING")

_ROAMING_RATES_EUR_PER_MB = {
    "francia": 0.02,
    "germania": 0.02,
    "spagna": 0.02,
    "svizzera": 0.18,
    "regno unito": 0.12,
    "stati uniti": 0.25,
    "usa": 0.25,
}

_OUTAGES_BY_AREA_PREFIX = {
    "02": "Nessun guasto noto nell'area di Milano.",
    "06": "Manutenzione programmata a Roma oggi 14:00-16:00 — possibili rallentamenti.",
    "011": "Guasto in corso a Torino, tecnici già sul posto, ETA 2 ore.",
}


@mcp.tool()
def get_roaming_rate(country: str) -> str:
    """Look up Meridian Telecom's per-MB data roaming rate for a country."""
    # mcp_tool.py's caller is honest about forwarding a best-effort guess
    # (often the raw caller utterance, not a clean argument) rather than an
    # LLM-extracted value — so this toy tool meets it halfway with a
    # substring match against its own small dataset, instead of requiring
    # an exact country name.
    text = country.strip().lower()
    for name, rate in _ROAMING_RATES_EUR_PER_MB.items():
        if name in text:
            return f"Tariffa roaming dati per {name}: €{rate:.2f}/MB."
    return f"Nessuna tariffa roaming trovata in '{country}' — verificare con l'operatore."


@mcp.tool()
def check_service_outage(area_code: str) -> str:
    """Check whether there's a known service outage for a telephone area code."""
    prefix = area_code.strip().lstrip("0")
    for known_prefix, status in _OUTAGES_BY_AREA_PREFIX.items():
        if prefix == known_prefix.lstrip("0"):
            return status
    return f"Nessun guasto noto per il prefisso '{area_code}'."


if __name__ == "__main__":
    mcp.run()
