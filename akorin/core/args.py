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
import argparse

from akorin.core.package import APP_DESCRIPTION
from akorin.core.package import APP_NAME
from akorin.core.package import APP_VERSION


def parse_arguments() -> argparse.Namespace:
  parser = argparse.ArgumentParser(prog=APP_NAME, description=APP_DESCRIPTION)
  parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {APP_VERSION}")

  return parser.parse_args()
