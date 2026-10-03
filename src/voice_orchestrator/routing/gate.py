"""Level 1 of the router: a deterministic eligibility gate.

This is the Parloa-style boundary — a boolean check on session state
(authenticated, region, depth, any extracted slot) that decides which
agents are even *candidates* before any model, lightweight or not, looks at
the utterance. It costs ~microseconds, and it is a boundary no LLM can talk
its way past: there is no prompt injection that makes `authenticated == true`
evaluate to true.

Expressions are parsed with `ast` and walked by hand against a whitelist of
node types — never `eval()` — because this file's whole job is to be a
trust boundary, and `eval()` on a config file (which may get edited by
someone other than the code's author) would defeat that purpose.
"""
from __future__ import annotations

import ast
import operator
from typing import Any

_ALLOWED_BINOPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}


class UnsafeExpression(ValueError):
    pass


def _eval_node(node: ast.AST, context: dict[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, context)
    if isinstance(node, ast.BoolOp):
        values = [_eval_node(v, context) for v in node.values]
        if isinstance(node.op, ast.And):
            return all(values)
        if isinstance(node.op, ast.Or):
            return any(values)
        raise UnsafeExpression(f"Unsupported bool op: {node.op}")
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _eval_node(node.operand, context)
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, context)
        for op, comparator in zip(node.ops, node.comparators):
            fn = _ALLOWED_BINOPS.get(type(op))
            if fn is None:
                raise UnsafeExpression(f"Unsupported comparison: {op}")
            right = _eval_node(comparator, context)
            if not fn(left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.Name):
        return context.get(node.id)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval_node(e, context) for e in node.elts]
    raise UnsafeExpression(f"Unsupported expression node: {type(node).__name__}")


def is_eligible(expression: str, context: dict[str, Any]) -> bool:
    """Evaluates an eligibility expression (e.g. "authenticated == true and
    depth <= 2") against the session context. An empty expression means
    "always eligible" — most agents won't restrict on anything."""
    expression = expression.strip()
    if not expression:
        return True
    # YAML-friendly lowercase booleans/null, since config authors write true/false/null.
    normalized = (
        expression.replace("true", "True").replace("false", "False").replace("null", "None")
    )
    try:
        tree = ast.parse(normalized, mode="eval")
    except SyntaxError as exc:
        raise UnsafeExpression(f"Could not parse eligibility expression {expression!r}: {exc}") from exc
    result = _eval_node(tree, context)
    return bool(result)
