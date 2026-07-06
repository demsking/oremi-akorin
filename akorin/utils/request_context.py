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
import json
from typing import Any


def request_context(context: dict[str, Any]) -> str | None:
  if not context:
    return None

  return json.dumps(context, default=str, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def contextualized_text(text: str, context: dict[str, Any]) -> str:
  serialized_context = request_context(context)

  if serialized_context is None:
    return text

  return f"{text}\n\nContext: {serialized_context}"
