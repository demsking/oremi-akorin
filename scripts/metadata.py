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
import os
import sys
import tomllib

_current_dir = os.path.dirname(os.path.abspath(__file__))
_pyproject_path = os.path.join(_current_dir, "..", "pyproject.toml")

with open(_pyproject_path, "rb") as file:
  project = tomllib.load(file)["project"]

key = sys.argv[1]

if key == "authors":
  value = []

  for author in project.get("authors", []):
    if "name" in author and "email" in author:
      value.append(f"{author['name']} <{author['email']}>")
    elif "name" in author:
      value.append(author["name"])
    elif "email" in author:
      value.append(author["email"])
elif key == "license":
  license_info = project.get("license", {})

  if isinstance(license_info, dict):
    value = license_info.get("text", license_info.get("file", ""))
  else:
    value = license_info
elif key == "repository":
  value = project.get("urls", {}).get("Source", "")
elif key == "documentation":
  value = project.get("urls", {}).get("Documentation", "")
else:
  value = project.get(key, "")

if isinstance(value, list):
  value = ", ".join(value)

print(value)
