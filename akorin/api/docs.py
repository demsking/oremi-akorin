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
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.responses import HTMLResponse

from akorin.core.package import HTDOCS_DIR
from akorin.core.package import PROJECT_DIRECTORY

router = APIRouter(prefix="/docs")

DOCUMENTATION_PATH = PROJECT_DIRECTORY / "DOCUMENTATION.md"
SERVICE_DESCRIPTION = (
  DOCUMENTATION_PATH.read_text(encoding="utf-8").replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
)


@router.get("/static/{file_path:path}", include_in_schema=False)
async def static_asset(file_path: str) -> FileResponse:
  asset = (HTDOCS_DIR / file_path).resolve()

  if HTDOCS_DIR not in asset.parents and asset != HTDOCS_DIR:
    raise HTTPException(status_code=404, detail="Static asset not found")

  if not asset.is_file():
    raise HTTPException(status_code=404, detail="Static asset not found")

  return FileResponse(asset)


@router.get("/", include_in_schema=False, response_class=HTMLResponse)
async def html_documentation():
  return f"""
    <!DOCTYPE html>
    <html>
      <head>
        <meta charset="utf-8"/>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Oremi Akọrin Documentation</title>
        <link rel="icon" href="./static/favicon.png">
      </head>
      <body>
        <div id="app"></div>
        <script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script>
        <script type="module">
          const response = await fetch('../openapi.json');
          const openapi = await response.json();
          const isGitlabPage = location.origin.includes('gitlab.io');

          openapi.info.title = 'Oremi Akọrin Documentation';
          openapi.info.description = `{SERVICE_DESCRIPTION}`;

          if (isGitlabPage) {{
            openapi.servers = [];
          }}

          Scalar.createApiReference('#app', {{
            title: 'Oremi Akọrin API',
            agent: {{
              disabled: true,
            }},
            content: openapi,
            hideClientButton: true,
            hideTestRequestButton: isGitlabPage,
            expandAllModelSections: false,
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
