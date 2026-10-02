"""Sicherer Formelparser für individuelle Rechenschritte.

Eigener AST-Auswerter statt eval/simpleeval: nur + - * / , Klammern, Zahlen, erlaubte
Variablen und min/max. Zahlen werden direkt aus dem Quelltext als Decimal gelesen
(kein Umweg über float). Alles andere wird abgelehnt.
"""

from __future__ import annotations

import ast
import re
from decimal import Decimal, DivisionByZero, InvalidOperation

MAX_LENGTH = 500
MAX_NODES = 200
FUNCTIONS = {"min": min, "max": max}


class FormulaError(ValueError):
    pass


def normalize(expression: str) -> str:
    """Deutsche Schreibweise erlauben: 2,6 -> 2.6; Argumente in min/max mit ; trennen (min(a; b))."""
    expression = re.sub(r"(?<=\d),(?=\d)", ".", expression)
    return expression.replace(";", ",").replace("×", "*").replace("÷", "/")


def parse(expression: str, allowed_names: set[str]) -> ast.Expression:
    if not isinstance(expression, str) or not expression.strip():
        raise FormulaError("Formel ist leer")
    expression = normalize(expression)
    if len(expression) > MAX_LENGTH:
        raise FormulaError(f"Formel ist länger als {MAX_LENGTH} Zeichen")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        hint = ""
        if expression.strip()[:1] in "*/+":
            hint = " Die Formel muss vollständig sein, z. B. current * 2,6 statt * 2,6."
        raise FormulaError(f"Formel ist unvollständig oder ungültig.{hint}") from exc
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_NODES:
        raise FormulaError("Formel ist zu komplex")
    for node in nodes:
        if isinstance(node, (ast.Expression, ast.Load, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.UAdd)):
            continue
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            continue
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            continue
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            continue
        if isinstance(node, ast.Name):
            if node.id not in allowed_names and node.id not in FUNCTIONS:
                raise FormulaError(f"Unbekannte Variable: {node.id}")
            continue
        if isinstance(node, ast.Call):
            if not (isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS) or node.keywords:
                raise FormulaError("Nur die Funktionen min() und max() sind erlaubt")
            if len(node.args) < 2:
                raise FormulaError("min()/max() brauchen mindestens zwei Werte")
            continue
        raise FormulaError(f"Nicht erlaubter Ausdruck: {type(node).__name__}")
    return tree


def evaluate(expression: str, variables: dict[str, Decimal]) -> Decimal:
    expression = normalize(expression)
    tree = parse(expression, set(variables))

    def ev(node) -> Decimal:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            text = ast.get_source_segment(expression, node)
            return Decimal(text.replace("_", ""))
        if isinstance(node, ast.Name):
            if node.id in FUNCTIONS:
                raise FormulaError(f"{node.id} muss aufgerufen werden")
            value = variables[node.id]
            if value is None:
                raise FormulaError(f"Variable {node.id} hat keinen Wert")
            return value
        if isinstance(node, ast.UnaryOp):
            v = ev(node.operand)
            return -v if isinstance(node.op, ast.USub) else v
        if isinstance(node, ast.BinOp):
            a, b = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Add):
                return a + b
            if isinstance(node.op, ast.Sub):
                return a - b
            if isinstance(node.op, ast.Mult):
                return a * b
            if b == 0:
                raise FormulaError("Division durch null")
            return a / b
        if isinstance(node, ast.Call):
            return FUNCTIONS[node.func.id](ev(a) for a in node.args)
        raise FormulaError("Nicht erlaubter Ausdruck")  # pragma: no cover

    try:
        return ev(tree)
    except (InvalidOperation, DivisionByZero) as exc:
        raise FormulaError("Rechenfehler in der Formel") from exc
