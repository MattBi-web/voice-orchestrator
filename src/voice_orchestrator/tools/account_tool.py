"""Mock external-API tool — stands in for the pattern of calling out to a
real backend (a billing system, a CRM) over HTTP. The call site is isolated
on purpose: swapping `_fetch_account` for a real `requests.get(...)` against
an actual billing API is the only change needed to make this real.
"""
import re

from ..agents.registry import AgentSpec
from ..state import CallSession
from .base import Tool, ToolResult

TRIGGERS = [
    "stato del mio account", "saldo", "la mia bolletta", "quanto devo pagare",
    "il mio conto", "importo da pagare", "scadenza fattura",
]

# Stand-in for a real account database/CRM lookup.
_FAKE_ACCOUNTS = {
    "default": {"balance_eur": 42.90, "due_date": "2026-10-15", "status": "al corrente"},
    "ACC-991": {"balance_eur": 118.40, "due_date": "2026-09-28", "status": "scaduta"},
}


def _fetch_account(account_number: str | None) -> dict:
    """Simulates a network call to a billing backend. Swap this function's
    body for a real HTTP call and nothing else in the tool needs to change."""
    return _FAKE_ACCOUNTS.get(account_number or "default", _FAKE_ACCOUNTS["default"])


class CheckAccountStatusTool(Tool):
    id = "check_account_status"
    description = "Looks up the caller's account balance and payment status (mock billing API)."

    def should_trigger(self, agent: AgentSpec, utterance: str, session: CallSession) -> bool:
        text = utterance.lower()
        return any(re.search(re.escape(t), text) for t in TRIGGERS)

    def run(self, agent: AgentSpec, utterance: str, session: CallSession) -> ToolResult:
        account = _fetch_account(session.slots.get("account_number"))
        session.slots["last_account_lookup"] = account
        return ToolResult(
            summary=(
                f"Account lookup result — balance: €{account['balance_eur']:.2f}, "
                f"due date: {account['due_date']}, status: {account['status']}. "
                "Answer the caller's question using exactly these figures."
            ),
            caller_text=(
                f"Il saldo del tuo conto è di {account['balance_eur']:.2f} euro, "
                f"con scadenza il {account['due_date']} (stato: {account['status']})."
            ),
            data=account,
        )
