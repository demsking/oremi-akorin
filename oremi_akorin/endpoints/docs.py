# Copyright 2024-2026 Sébastien Demanou. All Rights Reserved.
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
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from ..core.settings import Settings


def create_docs_endpoints(api: FastAPI, settings: Settings) -> None:
  def parse_path(path: str) -> str:
    return settings.api_root_path + path if len(settings.api_root_path) > 1 else path

  docs_path = parse_path("/docs")
  openapi_path = parse_path("/openapi.json")

  @api.get("/", include_in_schema=False)
  async def redirect_to_docs():
    return HTMLResponse(status_code=307, headers={"Location": docs_path})

  @api.get(docs_path, response_class=HTMLResponse, include_in_schema=False)
  async def html_documentation():
    return f"""
      <!DOCTYPE html>
      <html>
        <head>
          <meta charset="utf-8"/>
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>Oremi Akọrin Documentation</title>
        </head>
        <body>
          <div id="app"></div>
          <script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script>
          <script>
            Scalar.createApiReference('#app', {{
              title: 'Oremi Akọrin Documentation',
              agent: {{
                disabled: true,
              }},
              url: "{openapi_path}",
              hideClientButton: true,
              hideTestRequestButton: false,
              expandAllModelSections: true,
              showSidebar: true,
              showDeveloperTools: 'localhost',
              operationTitleSource: 'summary',
              theme: 'default',
              persistAuth: false,
              telemetry: false,
              layout: 'modern',
              isEditable: false,
              isLoading: false,
              hideModels: false,
              documentDownloadType: 'both',
              hideSearch: false,
              showOperationId: false,
              hideDarkModeToggle: false,
              withDefaultFonts: true,
              defaultOpenAllTags: false,
              expandAllResponses: false,
              orderSchemaPropertiesBy: 'alpha',
              orderRequiredPropertiesFirst: true,
              default: false,
            }});
          </script>
        </body>
      </html>
    """
