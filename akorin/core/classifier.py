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
from typing import Protocol
from typing import Sequence

from pydantic import BaseModel
from pydantic import Field


class ClassificationResult(BaseModel):
  """Structured result of a semantic classification call."""

  label: str = Field(min_length=1, description="The chosen option key (highest-probability label).")
  confidence: float = Field(ge=0.0, le=1.0, description="Distribution concentration in [0, 1]; not calibrated correctness.")
  probabilities: dict[str, float] = Field(
    default_factory=dict,
    description="Probability for every supplied label; values sum to 1 when the backend reports them.",
  )
  model: str | None = Field(default=None, description="Classifier model identifier reported by the backend, if any.")


class SemanticClassifier(Protocol):
  """Backend-agnostic semantic classifier used by the routing stage.

  Implementations must be asynchronous, must never perform blocking I/O, and must
  raise on infrastructure failures (unavailable, timeout, malformed response)
  instead of returning a guessed label. Concrete implementations are expected to
  reuse the application's shared HTTP client.
  """

  async def classify(self, text: str, labels: Sequence[str]) -> ClassificationResult: ...
