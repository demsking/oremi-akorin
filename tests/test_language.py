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
from akorin.utils.language import detect_language


def test_detects_supported_languages():
  assert detect_language("Quel temps fera-t-il demain à Paris ?") == "fr"
  assert detect_language("Pourquoi le ciel est bleu ? Explique-moi simplement.") == "fr"
  assert detect_language("What will the weather be tomorrow?") == "en"
