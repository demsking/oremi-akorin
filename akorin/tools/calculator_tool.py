# Copyright 2026 Sébastien Demanou. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
import ast
import logging
import math
import operator
from collections.abc import Callable
from typing import Any
from typing import ClassVar

from akorin.core.request import ProcessRequestContext
from akorin.core.tools import OllamaTool
from akorin.core.tools import ToolResult


logger = logging.getLogger(__name__)

_BINARY_OPERATORS: dict[type[ast.operator], Callable[[float, float], float]] = {
  ast.Add: operator.add,
  ast.Sub: operator.sub,
  ast.Mult: operator.mul,
  ast.Div: operator.truediv,
  ast.FloorDiv: operator.floordiv,
  ast.Mod: operator.mod,
  ast.Pow: operator.pow,
}

_UNARY_OPERATORS: dict[type[ast.unaryop], Callable[[float], float]] = {
  ast.UAdd: operator.pos,
  ast.USub: operator.neg,
}

_CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau}


class CalculatorTool(OllamaTool):
  name = "calculate"
  definition: ClassVar[dict[str, Any]] = {
    "type": "function",
    "function": {
      "name": name,
      "description": "Evaluate arithmetic accurately. Supports parentheses, +, -, *, /, //, %, **, pi, e, and tau.",
      "parameters": {
        "type": "object",
        "properties": {
          "expression": {
            "type": "string",
            "description": "Arithmetic expression, for example (12.5 * 4) + 7 or pi * 3 ** 2.",
          },
        },
        "required": ["expression"],
      },
    },
  }

  async def execute(self, arguments: dict[str, Any], context: ProcessRequestContext) -> ToolResult:
    expression = str(arguments.get("expression", "")).strip()

    try:
      if not expression or len(expression) > 200:
        raise ValueError("Expression must contain between 1 and 200 characters")

      value = self._evaluate(ast.parse(expression, mode="eval").body)

      if not math.isfinite(value) or abs(value) > 1e100:
        raise ValueError("Result is outside the supported range")
    except (SyntaxError, TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
      return ToolResult(name=self.name, data={"error": str(exc) or "Invalid expression"})

    return ToolResult(name=self.name, data={"expression": expression, "result": value})

  def _evaluate(self, node: ast.AST, depth: int = 0) -> float:
    if depth > 20:
      raise ValueError("Expression is too complex")

    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
      return float(node.value)

    if isinstance(node, ast.Name) and node.id in _CONSTANTS:
      return _CONSTANTS[node.id]

    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
      return _UNARY_OPERATORS[type(node.op)](self._evaluate(node.operand, depth + 1))

    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
      left = self._evaluate(node.left, depth + 1)
      right = self._evaluate(node.right, depth + 1)

      if isinstance(node.op, ast.Pow) and abs(right) > 100:
        raise ValueError("Exponent is outside the supported range")

      return _BINARY_OPERATORS[type(node.op)](left, right)

    raise ValueError("Expression contains an unsupported operation")
