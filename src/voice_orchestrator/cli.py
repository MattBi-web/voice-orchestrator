"""`voice-orchestrator chat|agents|route|eval` — see README for a walkthrough."""
import uuid

import typer
import yaml
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from . import config
from .agents.registry import AgentSpec, add_agent, load_family, remove_agent, save_family
from .llm import get_provider
from .orchestrator import handle_turn
from .routing.router import route
from .state import CallSession

app = typer.Typer(add_completion=False, help="A configurable family of voice agents with latency-first routing.")
agents_app = typer.Typer(help="Inspect or edit the agent family (config/agents.yaml).")
app.add_typer(agents_app, name="agents")
console = Console()


def _agent_tree(agent: AgentSpec, tree: Tree | None = None) -> Tree:
    label = f"[bold]{agent.id}[/bold] — {agent.name}"
    if agent.eligibility:
        label += f"  [dim](eligibility: {agent.eligibility})[/dim]"
    node = tree.add(label) if tree else Tree(label)
    for child in agent.children:
        _agent_tree(child, node)
    return node


@agents_app.command("list")
def agents_list():
    """Show the whole agent family tree."""
    root = load_family(config.AGENTS_FILE)
    console.print(_agent_tree(root))


@agents_app.command("add")
def agents_add(
    id: str = typer.Option(..., help="Unique agent id"),
    name: str = typer.Option(..., help="Display name"),
    description: str = typer.Option(..., help="One-line description, shown to the LLM fallback router"),
    parent: str = typer.Option(..., help="Id of the agent this one becomes a child of"),
    system_prompt: str = typer.Option("", help="System prompt for this agent"),
    triggers: str = typer.Option("", help="Comma-separated Level-2 keyword triggers"),
    tools: str = typer.Option("", help="Comma-separated tool ids"),
    knowledge: str = typer.Option("", help="Comma-separated knowledge markdown filenames"),
    eligibility: str = typer.Option("", help="Level-1 gate expression, e.g. 'authenticated == true'"),
):
    """Add a new agent (or sub-agent) to the family — no code changes needed."""
    root = load_family(config.AGENTS_FILE)
    new_agent = AgentSpec(
        id=id,
        name=name,
        description=description,
        system_prompt=system_prompt,
        eligibility=eligibility,
        triggers=[t.strip() for t in triggers.split(",") if t.strip()],
        tools=[t.strip() for t in tools.split(",") if t.strip()],
        knowledge=[k.strip() for k in knowledge.split(",") if k.strip()],
    )
    try:
        add_agent(root, parent, new_agent)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    save_family(root, config.AGENTS_FILE)
    console.print(f"[green]Added {id!r} under {parent!r}.[/green]")
    console.print(_agent_tree(root))


@agents_app.command("remove")
def agents_remove(id: str = typer.Argument(..., help="Agent id to remove (and its whole subtree)")):
    """Remove an agent (and any sub-agents under it) from the family."""
    root = load_family(config.AGENTS_FILE)
    try:
        removed = remove_agent(root, id)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    save_family(root, config.AGENTS_FILE)
    removed_ids = [a.id for a in removed.iter_subtree()]
    console.print(f"[green]Removed {removed_ids}.[/green]")
    console.print(_agent_tree(root))


@app.command(name="route")
def route_cmd(
    utterance: str,
    start: str = typer.Option("router", help="Agent id to route from"),
    set_: list[str] = typer.Option([], "--set", help="Session slot override, key=value (repeatable)"),
    provider_name: str = typer.Option(None, "--provider", help="fake|anthropic|openai|gemini"),
):
    """One-shot: test a single routing decision without a full conversation."""
    root = load_family(config.AGENTS_FILE)
    current = root.find(start)
    if current is None:
        console.print(f"[red]No agent with id={start!r}[/red]")
        raise typer.Exit(1)

    session = CallSession(call_id="route-test")
    for item in set_:
        key, _, value = item.partition("=")
        session.slots[key] = {"true": True, "false": False}.get(value.lower(), value)

    provider = get_provider(provider_name)
    decision = route(
        utterance,
        current,
        session,
        llm_fallback=lambda u, candidates, cur_id, s: provider.classify(u, candidates, cur_id, s),
    )
    console.print(f"Eligible: {decision.eligible_agents}")
    console.print(f"Resolved by: [bold]{decision.resolved_by}[/bold]")
    console.print(f"Chosen agent: [bold]{decision.chosen_agent_id}[/bold]")
    console.print(f"Reason: {decision.reason}")


@app.command()
def chat(
    authenticated: bool = typer.Option(True, help="Seed the session as authenticated (gates billing)"),
    provider_name: str = typer.Option(None, "--provider", help="fake|anthropic|openai|gemini"),
):
    """Interactive text simulation of a call. Type 'exit' to end, '/auth off'
    or '/auth on' to toggle the authenticated slot mid-call (demoes the gate)."""
    root = load_family(config.AGENTS_FILE)
    provider = get_provider(provider_name)
    session = CallSession(call_id=str(uuid.uuid4())[:8])
    session.slots["authenticated"] = authenticated

    console.print("[bold]Meridian Telecom[/bold] — digita 'exit' per terminare la chiamata.\n")
    while True:
        utterance = console.input("[bold cyan]Tu:[/bold cyan] ")
        if utterance.strip().lower() in {"exit", "quit"}:
            break
        if utterance.strip().lower() in {"/auth on", "/auth off"}:
            session.slots["authenticated"] = utterance.strip().lower().endswith("on")
            console.print(f"[dim](authenticated = {session.slots['authenticated']})[/dim]")
            continue

        result = handle_turn(session, root, utterance, provider)
        tag = f"[dim]({result.routing.resolved_by}" + (
            f", handoff→{result.agent.id}" if result.handed_off else ""
        ) + (f", tools={result.tool_ids_used}" if result.tool_ids_used else "") + ")[/dim]"
        console.print(f"[bold magenta]{result.agent.name}:[/bold magenta] {result.reply} {tag}")

    stats = session.routing_stats()
    console.print(f"\n[dim]Routing breakdown this call: {stats}[/dim]")


@app.command(name="eval")
def eval_cmd():
    """Run the built-in routing eval set and report hit-rate + which router
    level resolved each case (the number that backs the latency claim)."""
    from .eval_data import EVAL_SET

    root = load_family(config.AGENTS_FILE)
    provider = get_provider("fake")

    table = Table(title="Routing eval")
    table.add_column("From")
    table.add_column("Utterance")
    table.add_column("Expected")
    table.add_column("Got")
    table.add_column("Level")
    table.add_column("Hit?")

    hits = 0
    level_counts: dict[str, int] = {}
    for start_id, utterance, expected, slots in EVAL_SET:
        current = root.find(start_id)
        session = CallSession(call_id="eval")
        session.slots.update(slots)
        decision = route(
            utterance,
            current,
            session,
            llm_fallback=lambda u, candidates, cur_id, s: provider.classify(u, candidates, cur_id, s),
        )
        hit = decision.chosen_agent_id == expected
        hits += hit
        level_counts[decision.resolved_by] = level_counts.get(decision.resolved_by, 0) + 1
        table.add_row(
            start_id, utterance, expected, decision.chosen_agent_id, decision.resolved_by, "✅" if hit else "❌"
        )

    console.print(table)
    console.print(f"\nHit-rate: [bold]{hits}/{len(EVAL_SET)}[/bold]")
    console.print(f"Resolved by level: {level_counts}")


if __name__ == "__main__":
    app()
