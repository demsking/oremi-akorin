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
from .constants import Service


class OremiError(Exception):
  """Base exception for expected service failures."""


class ComponentUnavailable(OremiError):
  def __init__(self, component: Service, reason: str):
    super().__init__(f"{component} unavailable: {reason}")
    self.component = component
    self.reason = reason


class ComponentRequestError(OremiError):
  def __init__(self, component: str, reason: str, *, message_en: str, message_fr: str):
    super().__init__(f"{component} request error: {reason}")
    self.component = component
    self.reason = reason
    self.message_en = message_en
    self.message_fr = message_fr


class NoResultFound(OremiError):
  def __init__(self, service: str):
    super().__init__(f"{service} returned no result")
    self.service = service
