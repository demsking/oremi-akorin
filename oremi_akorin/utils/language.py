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
from ..core.constants import Language

FRENCH_MARKERS = {
  "avec",
  "bonjour",
  "comment",
  "demain",
  "météo",
  "pour",
  "quel",
  "quelle",
  "rappelle",
  "recherche",
  "trouve",
  "une",
}


def detect_language(text: str) -> Language:
  words = {word.strip(".,!?;:'\"").lower() for word in text.split()}

  if words & FRENCH_MARKERS or any(char in text.lower() for char in "àâçéèêëîïôùûü"):
    return Language.FR

  return Language.EN
