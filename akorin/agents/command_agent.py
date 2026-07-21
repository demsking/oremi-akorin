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
from __future__ import annotations

from pydantic import BaseModel
from pydantic import Field
from pydantic_ai import ModelSettings

from akorin.core.agent import AgentClient
from akorin.core.service import Service


SYSTEM_PROMPT = (
  "You are a request router.\n\n"
  "Return only valid JSON matching this schema:\n"
  '{"service":"<service>","confidence":<0-1>}\n\n'
  "Valid services:\n"
  "- isinmi: reminders, alarms, timers, calendar, scheduling.\n"
  "- ojo: current or future weather, forecast, temperature, air quality, pollen, alerts, or warnings for a place.\n"
  "- rediyo: radio stations.\n"
  "- kansa: podcasts.\n"
  "- isakoso: smart home and Zigbee devices, including lights, lamps, switches, plugs, thermostats, blinds, shutters, "
  "locks, and commands such as turn on, turn off, allume, éteins, ouvre, ferme, active, désactive.\n"
  "- chat: everything else, including current time, current date, or current day.\n\n"
  "Examples:\n"
  '- {"text":"What\'s the weather like in Lagos?"} -> {"service":"ojo","confidence":0.95}\n'
  '- {"text":"Quel temps fait-il à Paris ?"} -> {"service":"ojo","confidence":0.95}\n'
  '- {"text":"Are pollen levels high in Lyon today?"} -> {"service":"ojo","confidence":0.95}\n'
  '- {"text":"Est-ce qu\'il y a du pollen à Lyon en ce moment ?"} -> {"service":"ojo","confidence":0.95}\n'
  '- {"text":"Turn on the living room lights and set brightness to 80%"} -> {"service":"isakoso","confidence":0.98}\n'
  '- {"text":"Allume les lumières du salon et mets la luminosité à 80%"} -> {"service":"isakoso","confidence":0.98}\n'
  '- {"text":"Allume la lumière de la chambre"} -> {"service":"isakoso","confidence":0.98}\n'
  '- {"text":"Éteins la lampe du salon"} -> {"service":"isakoso","confidence":0.98}\n'
  '- {"text":"Éteins la lumière de la chambre"} -> {"service":"isakoso","confidence":0.98}\n'
  '- {"text":"Turn on the bedroom light"} -> {"service":"isakoso","confidence":0.98}\n'
  '- {"text":"Can you explain why the sky is blue like I\'m five?"} -> {"service":"chat","confidence":0.96}\n'
  '- {"text":"Pourquoi le ciel est bleu ? Explique-moi simplement."} -> {"service":"chat","confidence":0.96}\n'
  '- {"text":"Why is the sky blue?"} -> {"service":"chat","confidence":0.96}\n'
  '- {"text":"Quelle heure est-il ?"} -> {"service":"chat","confidence":0.85}\n\n'
  '- {"text":"Remind me to call Ada tomorrow at 9 AM"} -> {"service":"isinmi","confidence":0.96}\n'
  '- {"text":"Rappelle-moi de sortir les poubelles ce soir à 20h"} -> {"service":"isinmi","confidence":0.96}\n'
  '- {"text":"Schedule a weekly sync meeting every Monday at 10 AM"} -> {"service":"isinmi","confidence":0.96}\n'
  '- {"text":"Planifie un cours de yoga tous les mardis à 18h30"} -> {"service":"isinmi","confidence":0.96}\n'
  '- {"text":"Play BBC Radio 1"} -> {"service":"rediyo","confidence":0.96}\n'
  '- {"text":"Mets France Inter s\'il te plaît"} -> {"service":"rediyo","confidence":0.96}\n'
  '- {"text":"Play the latest episode of The Daily podcast"} -> {"service":"kansa","confidence":0.96}\n'
  '- {"text":"Joue le dernier épisode de Transfert"} -> {"service":"kansa","confidence":0.96}\n\n'
  "Return nothing except the JSON object."
)


class RouteDecision(BaseModel):
  service: Service
  confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class CommandAgent(AgentClient[RouteDecision]):
  SYSTEM_PROMPT = SYSTEM_PROMPT
  RESULT_TYPE = RouteDecision
  RESPONSE_FORMAT = "json"

  def _get_model_settings(self) -> ModelSettings:
    return ModelSettings(
      temperature=0,
      max_tokens=80,
      timeout=self.settings.llm_request_timeout,
      seed=0,
      thinking=False,
    )

  async def classify(self, message: str) -> RouteDecision:
    return await self._run(message)
