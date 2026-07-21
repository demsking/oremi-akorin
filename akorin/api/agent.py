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
from fastapi import Body
from fastapi import Request
from fastapi import status
from fastapi.openapi.models import Example

from akorin.core.context import get_app_context_orchestrator
from akorin.core.request import ProcessRequest
from akorin.core.response import ProcessResponse


API_TAG_METADATA = {
  "name": "Agent Processing",
  "description": (
    "Process natural-language requests and route them to LLM model, built-in "
    "tools, knowledge sources, or configured Oremi services."
  ),
}


router = APIRouter(prefix="/agent", tags=[API_TAG_METADATA["name"]])

OREMI_DEVICE_PREFERENCES_EXAMPLE = {
  "language": "fr",
  "location": "Deido, Douala, Cameroun",
  "timezone": "Africa/Douala",
  "temperature_unit": "celsius",
  "preferred_currency": "XAF",
  "measurement_system": "metric",
  "distance_unit": "kilometer",
  "time_format": "24h",
  "date_format": "DD/MM/YYYY",
  "first_day_of_week": "monday",
  "latitude": 4.0637626,
  "longitude": 9.7151827,
  "address": "Deido, Douala I, Communauté urbaine de Douala, Wouri, Littoral, Cameroon",
  "datetime": "2026-07-10T07:36:49.673555+02:00",
}


PAYLOAD_EXAMPLES: dict[str, Example] = {
  # --- WEATHER ---
  "Weather forecast (EN)": {
    "summary": "Weather forecast (EN)",
    "description": "Requesting weather details with localized imperial/metric preferences via context.",
    "value": ProcessRequest.model_validate(
      {
        "message": "What's the weather like in Lagos?",
        "context": {"timezone": "Africa/Lagos", "temperature_unit": "celsius"},
      }
    ),
  },
  "Météo (FR)": {
    "summary": "Prévisions météo (FR)",
    "description": "Demande d'informations météo pour une ville spécifique.",
    "value": ProcessRequest.model_validate({"message": "Quel temps fait-il à Paris ?"}),
  },
  "Weather with Oremi Device context": {
    "summary": "Weather with Oremi Device context",
    "description": "Uses the device preferences envelope; Akọrin forwards only weather-relevant context to the weather service.",
    "value": ProcessRequest.model_validate(
      {
        "message": "Quel temps fait-il ici ?",
        "context": OREMI_DEVICE_PREFERENCES_EXAMPLE,
        "tags": ["device_id:oremi-device"],
      }
    ),
  },
  # --- POLLEN ---
  "Pollen count (EN)": {
    "summary": "Pollen & Allergen report (EN)",
    "description": "Checks local pollen levels using geography coordinates.",
    "value": ProcessRequest.model_validate(
      {
        "message": "Are pollen levels high in Lyon today?",
        "context": {"lat": 45.7640, "lon": 4.8357, "timezone": "Europe/Paris"},
      }
    ),
  },
  "Alerte Pollen (FR)": {
    "summary": "Indice de pollen (FR)",
    "description": "Vérification des risques d'allergies aux pollens (RNSA).",
    "value": ProcessRequest.model_validate(
      {
        "message": "Est-ce qu'il y a du pollen à Lyon en ce moment ?",
        "context": {"lat": 45.7640, "lon": 4.8357, "timezone": "Europe/Paris"},
      }
    ),
  },
  # --- ZIGBEE ---
  "Zigbee device command": {
    "summary": "Zigbee device command",
    "description": "Routes smart-home commands without forwarding unrelated device preferences to Zigbee processing.",
    "value": ProcessRequest.model_validate(
      {
        "message": "Allume la lumière de la chambre",
        "context": OREMI_DEVICE_PREFERENCES_EXAMPLE,
        "tags": ["room:bedroom", "device_id:oremi-device"],
      }
    ),
  },
  "Control Zigbee device (EN)": {
    "summary": "Control a Zigbee device",
    "description": "Explicitly passing device parameters and the intent via natural language, with a localized device room tag.",
    "value": ProcessRequest.model_validate(
      {
        "message": "Turn on the living room lights and set brightness to 80%",
        "tags": ["room:living-room"],
      }
    ),
  },
  "Contrôler un appareil Zigbee (FR)": {
    "summary": "Contrôler un appareil Zigbee",
    "description": "Envoi d'une commande domotique en langage naturel avec contexte de l'appareil ciblé.",
    "value": ProcessRequest.model_validate(
      {
        "message": "Allume les lumières du salon et mets la luminosité à 80%",
        "tags": ["room:living-room"],
      }
    ),
  },
  "Allumer la lumière de la chambre (FR)": {
    "summary": "Contrôler un appareil Zigbee",
    "description": "Envoi d'une commande domotique en langage naturel avec contexte de l'appareil ciblé.",
    "value": ProcessRequest.model_validate(
      {
        "message": "Allume la lumière de la chambre",
        "tags": ["room:bedroom"],
      }
    ),
  },
  "Éteindre la lumière de la chambre (FR)": {
    "summary": "Éteindre un appareil Zigbee",
    "description": "Commande vocale ou textuelle pour éteindre un point de lumière spécifique dans la chambre.",
    "value": ProcessRequest.model_validate(
      {
        "message": "Éteins la lumière de la chambre",
        "tags": ["room:bedroom"],
      }
    ),
  },
  # --- CHAT ---
  "General Chat (EN)": {
    "summary": "Chitchat / Assistant interaction (EN)",
    "description": "A casual or open-ended conversation scenario handled by the LLM core.",
    "value": ProcessRequest.model_validate(
      {"message": "Can you explain why the sky is blue like I'm five?", "tags": ["user_id:alex", "source:web-app"]}
    ),
  },
  "Discussion générale (FR)": {
    "summary": "Discussion / Chat (FR)",
    "description": "Une interaction ouverte ou une question de culture générale.",
    "value": ProcessRequest.model_validate(
      {"message": "Pourquoi le ciel est bleu ? Explique-moi simplement.", "tags": ["user_id:alex", "source:web-app"]}
    ),
  },
  # --- REMINDER ---
  "Set a reminder (EN)": {
    "summary": "Create a simple reminder (EN)",
    "description": "Sets a transient reminder using relative time parsing.",
    "value": ProcessRequest.model_validate(
      {
        "message": "Remind me to call Ada tomorrow at 9 AM",
        "context": {"timezone": "Europe/Paris"},
        "tags": ["device_id:iphone-14"],
      }
    ),
  },
  "Créer un rappel (FR)": {
    "summary": "Créer un rappel (FR)",
    "description": "Planifie un rappel contextuel basé sur une heure relative.",
    "value": ProcessRequest.model_validate(
      {
        "message": "Rappelle-moi de sortir les poubelles ce soir à 20h",
        "context": {"timezone": "Europe/Paris"},
        "tags": ["room:kitchen"],
      }
    ),
  },
  "Créer un rappel avec un context élargie (FR)": {
    "summary": "Reminder with Oremi Device context",
    "description": "Uses device date and time preferences while keeping unrelated location and unit preferences out of Isinmi.",
    "value": ProcessRequest.model_validate(
      {
        "message": "Rappelle-moi de sortir les poubelles ce soir à 20h",
        "context": OREMI_DEVICE_PREFERENCES_EXAMPLE,
        "tags": ["device_id:oremi-device"],
      }
    ),
  },
  # --- SCHEDULE ---
  "Schedule recurring event (EN)": {
    "summary": "Schedule isinmi/recurring event (EN)",
    "description": "Creates a permanent or recurring isinmi event or schedule automation.",
    "value": ProcessRequest.model_validate(
      {"message": "Schedule a weekly sync meeting every Monday at 10 AM", "context": {"timezone": "America/New_York"}}
    ),
  },
  "Planifier un événement (FR)": {
    "summary": "Planifier une tâche/réunion (FR)",
    "description": "Ajoute un événement récurrent ou fixe dans l'agenda.",
    "value": ProcessRequest.model_validate(
      {"message": "Planifie un cours de yoga tous les mardis à 18h30", "context": {"timezone": "Europe/Paris"}}
    ),
  },
  # --- RADIO ---
  "Play Radio (EN)": {
    "summary": "Stream live radio station (EN)",
    "description": "Matches a station name and triggers an audio stream playback intent.",
    "value": ProcessRequest.model_validate({"message": "Play BBC Radio 1"}),
  },
  "Lancer la radio (FR)": {
    "summary": "Lancer une radio en direct (FR)",
    "description": "Recherche et diffuse un flux de radio en direct.",
    "value": ProcessRequest.model_validate({"message": "Mets France Inter s'il te plaît"}),
  },
  # --- PODCAST ---
  "Play Podcast (EN)": {
    "summary": "Stream latest podcast episode (EN)",
    "description": "Looks up a specific podcast series to fetch the newest RSS episode link.",
    "value": ProcessRequest.model_validate(
      {"message": "Play the latest episode of The Daily podcast", "tags": ["source:voice"]}
    ),
  },
  "Lancer un podcast (FR)": {
    "summary": "Lancer un podcast (FR)",
    "description": "Recherche le dernier épisode d'un podcast francophone.",
    "value": ProcessRequest.model_validate({"message": "Joue le dernier épisode de Transfert", "tags": ["source:voice"]}),
  },
}

RESPONSE_EXAMPLES: dict[str, Example] = {
  # --- WEATHER ---
  "weather": {
    "summary": "Weather response",
    "value": ProcessResponse.model_validate(
      {
        "ok": True,
        "input": "What's the weather like in Lagos?",
        "language": "en",
        "service": "ojo",
        "message": "It's currently 28.4°C in Lagos with clear skies. Enjoy your day!",
        "data": {
          "provider": "Open-Météo",
          "input": "What's the weather like in Lagos?",
          "services": ["weather"],
          "message": "It's currently 28.4°C in Lagos with clear skies. Enjoy your day!",
          "data": {
            "weather": {
              "temperature": "28.4°C",
              "humidity": None,
              "wind_speed": None,
              "sunrise": "06:37:00",
              "sunset": "19:05:00",
            }
          },
          "location": {
            "type": "city",
            "name": "Lagos",
            "boundingbox": [6.2950575, 6.6150575, 3.2341795, 3.5541795],
            "lat": 6.4550575,
            "lon": 3.3941795,
            "addresstype": "city",
            "display_name": "Lagos, Lagos Island, Lagos State, 100242, Nigeria",
            "address": {
              "country": "Nigeria",
              "country_code": "ng",
              "region": None,
              "postcode": "100242",
              "road": None,
              "town": None,
              "municipality": None,
              "county": "Lagos Island",
              "state": "Lagos State",
              "city": "Lagos",
            },
          },
        },
        "confidence": 0.95,
        "commands": [],
      }
    ),
  },
  "tool": {
    "summary": "Native tool response",
    "value": ProcessResponse.model_validate(
      {
        "ok": True,
        "input": "What time is it in Paris?",
        "language": "en",
        "service": "tool",
        "message": "It is 07:36 in Paris.",
        "data": {
          "tools": [
            {
              "name": "get_current_datetime",
              "datetime": "2026-07-10T07:36:49.673555+02:00",
              "date": "2026-07-10",
              "time": "07:36:49",
              "timezone": "Africa/Douala",
            }
          ]
        },
        "confidence": 1.0,
        "commands": [],
      }
    ),
  },
  "more_information_required": {
    "summary": "More information required",
    "value": ProcessResponse.model_validate(
      {
        "ok": False,
        "input": "Are there weather alerts?",
        "language": "en",
        "service": "ojo",
        "message": "Please share a location so I can check alerts for that area.",
        "data": {"error": {"type": "more_information_required"}},
        "confidence": 0.95,
        "commands": [],
      }
    ),
  },
}


@router.post(
  path="/",
  summary="Process a natural-language request",
  response_model=ProcessResponse,
  status_code=status.HTTP_200_OK,
  responses={
    200: {
      "description": (
        "The request was processed. Inspect `ok` to distinguish a successful result from an expected service or input failure."
      ),
      "content": {"application/json": {"examples": RESPONSE_EXAMPLES}},
    },
    500: {
      "description": "An unexpected processing error occurred.",
      "content": {"application/json": {"example": {"detail": "Internal Server Error"}}},
    },
  },
)
async def process_user_input(
  request: Request,
  payload: ProcessRequest = Body(
    ...,
    description=(
      "The user's text plus optional language, service context, and caller-defined tags. "
      "Context requirements depend on the selected service."
    ),
    openapi_examples=PAYLOAD_EXAMPLES,
  ),
) -> ProcessResponse:
  """Process and route a natural-language request.

  The endpoint normalizes the input, detects its language when `language` is
  omitted, and routes the request to the best available capability:

  - conversational answers and native date/time, calculator, or conversion tools;
  - configured scheduling, weather, radio, podcast, or Zigbee services.

  HTTP 200 responses include the processing result. Inspect `ok` to distinguish
  successful results from expected service or input failures.
  """
  orchestrator = get_app_context_orchestrator(request)

  return await orchestrator.process(payload)
