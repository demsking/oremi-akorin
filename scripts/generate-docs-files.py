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
from fastapi.testclient import TestClient

from akorin import app
from akorin.core.package import HTDOCS_DIR


HTDOCS_INDEX_FILE = HTDOCS_DIR / "index.html"
HTDOC_OPENAPI_FILE = HTDOCS_DIR / "openapi.json"

client = TestClient(app)


def generate_openapi():
  response = client.get("/openapi.json")
  openapi = response.content

  HTDOC_OPENAPI_FILE.write_bytes(openapi)


def generate_static_doc():
  response = client.get("/docs")
  content = response.content.decode("utf-8").replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")

  HTDOCS_INDEX_FILE.write_text(content)


if __name__ == "__main__":
  generate_openapi()
  generate_static_doc()
