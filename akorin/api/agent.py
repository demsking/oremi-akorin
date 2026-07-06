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

from ..core.context import AppContext
from ..core.models import ProcessRequest
from ..core.models import ProcessResponse


API_TAG_METADATA = {
  "name": "Agent Processing",
  "description": (
    "Process English or French natural-language requests and route them to "
    "LLM model, built-in tools, knowledge sources, or configured Oremi services."
  ),
}


router = APIRouter(prefix="/agent", tags=[API_TAG_METADATA["name"]])


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
      "content": {
        "application/json": {
          "examples": {
            "weather": {
              "summary": "Weather result",
              "value": {
                "ok": True,
                "input": "What's the weather like in Lagos?",
                "language": "en",
                "service": "weather",
                "message": (
                  "It's quite warm in Lagos with temperatures around 26°C. Humidity is at 82%, so it feels a bit sticky."
                  "With winds blowing at about 12 km/h from the northeast, and considering the sunset will be at 6 PM today, "
                  "that might make for some pleasant evenings. Take a hat and maybe an umbrella if rain is in the forecast."
                ),
                "data": {
                  "provider": "Open-Météo",
                  "input": "What's the weather like in Lagos?",
                  "services": ["weather"],
                  "message": (
                    "It's quite warm in Lagos with temperatures around 26°C."
                    "Humidity is at 82%, so it feels a bit sticky. With winds blowing at about 12 km/h from the northeast, "
                    "and considering the sunset will be at 6 PM today, that might make for some pleasant evenings. Take a "
                    "hat and maybe an umbrella if rain is in the forecast."
                  ),
                  "data": {
                    "weather": {
                      "temperature": "26.4°C",
                      "humidity": "82%",
                      "wind_speed": "12.3 km/h",
                      "sunrise": "05:33:00",
                      "sunset": "18:03:00",
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
              },
            },
            "tool": {
              "summary": "Built-in tool result",
              "value": {
                "ok": True,
                "input": "What is 18 * 4?",
                "language": "en",
                "service": "tool",
                "message": "18 multiplied by 4 is 72.",
                "data": {"tools": [{"name": "calculate", "expression": "18 * 4", "result": 72}]},
                "confidence": 1.0,
              },
            },
            "more_information_required": {
              "summary": "Expected input failure",
              "value": {
                "ok": False,
                "input": "Set an alarm for tomorrow morning",
                "language": "en",
                "service": "isinmi",
                "message": "Please specify your timezone so I can schedule this at the correct time.",
                "data": {"error": {"type": "more_information_required"}},
                "confidence": 0.98,
              },
            },
          }
        }
      },
    },
    422: {
      "description": "The JSON body does not match the request schema.",
      "content": {
        "application/json": {
          "example": {
            "detail": [
              {
                "type": "string_too_short",
                "loc": ["body", "message"],
                "msg": "String should have at least 1 character",
                "input": "",
                "ctx": {"min_length": 1},
              }
            ]
          }
        }
      },
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
    openapi_examples={
      "weather": {
        "summary": "Weather forecast",
        "description": "Timezone and temperature unit are forwarded to the weather service.",
        "value": {
          "message": "What's the weather like in Lagos?",
          "language": "en",
          "context": {"timezone": "Africa/Lagos", "temperature_unit": "celsius"},
        },
      },
      "reminder": {
        "summary": "Schedule a reminder",
        "description": "Isinmi requires an IANA timezone to resolve relative dates correctly.",
        "value": {
          "message": "Remind me to call Ada tomorrow at 9 AM",
          "language": "en",
          "context": {"timezone": "Europe/Paris"},
          "tags": {"user": "ada"},
        },
      },
      "zigbee": {
        "summary": "Control a Zigbee device",
        "description": "Device and state can be inferred from text or supplied explicitly in context.",
        "value": {
          "message": "Turn off the bedroom lamp",
          "language": "en",
          "context": {"device": "bedroom_lamp", "state": "OFF"},
        },
      },
      "restaurant_booking": {
        "summary": "Book a restaurant table",
        "description": "Supports date/time parsing and party size requirements for reservation services.",
        "value": {
          "message": "Book a table for 4 at that Italian place downtown for Saturday at 8 PM",
          "language": "en",
          "context": {
            "timezone": "America/New_York",
            "party_size": 4,
            "cuisine_preference": "Italian",
            "booking_service": "open_table",
          },
          "tags": {"customer_id": "cust_12345", "loyalty_tier": "gold"},
        },
      },
      "flight_status": {
        "summary": "Track a flight",
        "description": "Accepts flight number, airline, or route information to fetch real-time status.",
        "value": {
          "message": "Is flight BA284 from London to Tokyo on time?",
          "language": "en",
          "context": {
            "flight_number": "BA284",
            "airline": "British Airways",
            "departure_airport": "LHR",
            "arrival_airport": "NRT",
            "date": "2026-06-28",
          },
          "tags": {"request_id": "req_98765", "source": "mobile_app"},
        },
      },
      "medical_appointment": {
        "summary": "Schedule a medical appointment",
        "description": "Requires patient ID, provider specialty, and available date/time preferences.",
        "value": {
          "message": "I need to see Dr. Martinez next week for my annual checkup",
          "language": "en",
          "context": {
            "patient_id": "P12345",
            "provider_name": "Dr. Martinez",
            "specialty": "general_practice",
            "preferred_days": ["Monday", "Wednesday", "Friday"],
            "timezone": "America/Los_Angeles",
            "clinic_location": "downtown",
          },
          "tags": {"department": "primary_care", "urgent": "false", "insurance": "blue_cross"},
        },
      },
      "ecommerce_return": {
        "summary": "Process a product return",
        "description": "Order number and return reason are required for processing refunds/exchanges.",
        "value": {
          "message": "I want to return the blue sweater because it's too small",
          "context": {
            "order_id": "ORD-7890",
            "product_sku": "SWE-125-M",
            "return_reason": "size_issue",
            "return_method": "mail_in",
            "refund_preference": "store_credit",
          },
          "tags": {"customer_support": "returns_team", "priority": "standard"},
        },
      },
      "smart_home_scene": {
        "summary": "Activate a smart home scene",
        "description": "Executes predefined scene with multiple device states simultaneously.",
        "value": {
          "message": "It's movie time",
          "context": {
            "scene": "movie_night",
            "devices": {
              "living_room_lights": {"state": "OFF", "brightness": 0},
              "projector": {"state": "ON", "input": "hdmi1"},
              "speakers": {"state": "ON", "volume": 40, "source": "bluetooth"},
              "curtains": {"state": "CLOSED"},
              "temperature": {"mode": "cool", "setpoint": 22},
            },
          },
          "tags": {"user": "family_room", "automation": "scene_trigger"},
        },
      },
      "package_tracking": {
        "summary": "Track package delivery",
        "description": "Supports both tracking numbers and approximate delivery estimates.",
        "value": {
          "message": "Where's my package from Amazon?",
          "language": "en",
          "context": {
            "tracking_number": "1Z999AA10123456784",
            "carrier": "UPS",
            "expected_delivery_range": {"start": "2026-06-28", "end": "2026-07-02"},
            "destination_zip": "90210",
          },
          "tags": {"ecommerce_platform": "amazon", "order_date": "2026-06-20"},
        },
      },
      "investment_analysis": {
        "summary": "Get investment portfolio analysis",
        "description": "Requires portfolio holdings and time horizon for risk assessment.",
        "value": {
          "message": "How are my tech stocks performing this quarter?",
          "context": {
            "portfolio_id": "PF-4321",
            "sectors": ["technology", "semiconductors", "cloud_computing"],
            "timeframe": "Q2_2026",
            "metrics": ["return_percentage", "volatility", "sharpe_ratio"],
            "benchmark": "NASDAQ",
          },
          "tags": {"account_type": "retirement", "risk_tolerance": "aggressive"},
        },
      },
      "customer_feedback": {
        "summary": "Analyze customer feedback",
        "description": "Sentiment analysis and categorization of support tickets or reviews.",
        "value": {
          "message": "The customer said the app is great but the checkout process was confusing",
          "language": "en",
          "context": {
            "feedback_type": "support_ticket",
            "ticket_id": "TKT-2026-4567",
            "product_area": "checkout_flow",
            "sentiment_analysis": True,
            "category": "ui_ux",
            "priority": "medium",
          },
          "tags": {"source": "zendesk", "agent_assigned": "jane_smith"},
        },
      },
      "language_translation": {
        "summary": "Translate text with context",
        "description": "Preserves terminology and style based on domain-specific glossaries.",
        "value": {
          "message": "The system requires validation before deployment to production",
          "language": "en",
          "context": {
            "target_language": "es",
            "domain": "software_development",
            "style": "technical",
            "glossary": {"validation": "validación", "deployment": "despliegue", "production": "entorno_de_producción"},
          },
          "tags": {"project": "documentation", "version": "2.0", "translator": "automated"},
        },
      },
      "learning_quiz": {
        "summary": "Generate an educational quiz",
        "description": "Creates questions with difficulty levels based on subject and topic.",
        "value": {
          "message": "Create a quiz about World War II history for my 10th grade students",
          "context": {
            "subject": "history",
            "topic": "World_War_II",
            "grade_level": "10",
            "number_of_questions": 15,
            "difficulty": "medium",
            "question_formats": ["multiple_choice", "true_false"],
            "answer_key_required": True,
          },
          "tags": {"teacher_id": "tchr_5678", "class_section": "A"},
        },
      },
      "traduction_document": {
        "summary": "Traduction d'un document technique",
        "description": "Traduit un texte vers une langue cible en conservant le jargon technique.",
        "value": {
          "message": "Le protocole MQTT utilise un modèle publish-subscribe pour la communication IoT",
          "language": "fr",
          "context": {
            "target_language": "en",
            "domain": "technology",
            "preserve_terms": ["MQTT", "publish-subscribe", "IoT"],
          },
          "tags": {"project": "docs_v2", "author": "marie"},
        },
      },
      "commande_maison": {
        "summary": "Scène d'ambiance domotique",
        "description": "Active une scène personnalisée avec plusieurs appareils connectés.",
        "value": {
          "message": "Mets l'ambiance cinéma dans le salon",
          "context": {
            "scene": "cinema_mode",
            "devices": {"lights": "dim_20%", "curtains": "closed", "tv": "on", "soundbar": "cinema_profile"},
            "room": "salon",
          },
        },
      },
      "alerte_medicale": {
        "summary": "Suivi de santé patient",
        "description": "Analyse des symptômes avec contexte médical et historique.",
        "value": {
          "message": "Le patient présente une fièvre persistante depuis 3 jours",
          "language": "fr",
          "context": {
            "patient_id": "P-2024-789",
            "symptoms": ["fever", "cough", "fatigue"],
            "last_checkup": "2026-06-20",
            "medications": ["paracetamol", "amoxicillin"],
            "urgency_level": "moderate",
          },
          "tags": {"doctor": "dupont", "department": "urgences", "shift": "nuit"},
        },
      },
      "reservation_restaurant": {
        "summary": "Réservation pour un groupe",
        "description": "Gère les préférences alimentaires et les contraintes de capacité.",
        "value": {
          "message": "Réserve une table pour 8 personnes vendredi soir à 20h",
          "language": "fr",
          "context": {
            "restaurant_id": "le_marcel",
            "date": "2026-07-03",
            "time": "20:00",
            "guests": 8,
            "dietary_restrictions": ["vegetarian", "gluten_free"],
            "special_occasion": "anniversaire",
            "preferred_area": "terrasse",
          },
          "tags": {"source": "mobile_app", "customer_loyalty": "gold"},
        },
      },
      "analyse_financiere": {
        "summary": "Rapport financier personnalisé",
        "description": "Génère une analyse basée sur des données financières et des indicateurs.",
        "value": {
          "message": "Quelle est la performance de mon portefeuille ce trimestre ?",
          "context": {
            "portfolio_id": "PF-456",
            "timeframe": "Q2_2026",
            "metrics": ["ROI", "volatility", "sharpe_ratio"],
            "comparison_benchmark": "SBF120",
            "risk_tolerance": "moderate",
            "currency": "EUR",
          },
          "tags": {"advisor": "martin", "client_segment": "premium"},
        },
      },
      "commande_inventaire": {
        "summary": "Gestion de stock automatique",
        "description": "Déclenche une commande de réapprovisionnement basée sur les seuils.",
        "value": {
          "message": "Le stock de café est presque épuisé, il faut commander",
          "language": "fr",
          "context": {
            "product_sku": "COF-001",
            "current_stock": 12,
            "minimum_threshold": 50,
            "quantity_to_order": 100,
            "supplier_id": "supplier_france",
            "delivery_priority": "express",
            "warehouse": "lyon_central",
          },
          "tags": {"requester": "logistique", "department": "approvisionnement"},
        },
      },
      "recherche_emploi": {
        "summary": "Recherche d'offres d'emploi ciblée",
        "description": "Filtre les offres selon les compétences et localisation du candidat.",
        "value": {
          "message": "Trouve des postes de développeur Python dans la région parisienne",
          "language": "fr",
          "context": {
            "position": "développeur Python senior",
            "location": "Île-de-France",
            "experience_years": 5,
            "skills": ["Python", "FastAPI", "PostgreSQL", "Docker"],
            "remote": "hybrid",
            "salary_expectation_min": 55000,
            "salary_currency": "EUR",
            "contract_type": "CDI",
          },
          "tags": {"candidate_id": "C-123", "recruiter": "rh_tech"},
        },
      },
      "optimisation_trajet": {
        "summary": "Calcul d'itinéraire multi-étapes",
        "description": "Optimise un trajet avec plusieurs arrêts et contraintes de temps.",
        "value": {
          "message": "Quel est le meilleur itinéraire pour mes livraisons de demain ?",
          "context": {
            "stops": [
              {"address": "12 rue de la Paix, Paris", "time_window_start": "08:00", "time_window_end": "09:30"},
              {"address": "45 avenue des Champs, Paris", "time_window_start": "10:00", "time_window_end": "12:00"},
              {"address": "78 boulevard Saint-Germain, Paris", "time_window_start": "14:00", "time_window_end": "16:00"},
            ],
            "vehicle_type": "van",
            "max_weight": 800,
            "fuel_type": "electric",
            "optimization_criteria": "time",
            "traffic_mode": "real_time",
          },
          "tags": {"fleet_id": "F-789", "driver": "sophie"},
        },
      },
      "recommandation_culturelle": {
        "summary": "Recommandation de films personnalisée",
        "description": "Propose des films selon l'humeur et les préférences de l'utilisateur.",
        "value": {
          "message": "J'ai envie d'un film qui fait peur mais pas trop",
          "language": "fr",
          "context": {
            "genres": ["horror", "thriller", "comedy"],
            "max_rating": 16,
            "platforms": ["netflix", "prime_video"],
            "release_year_min": 2020,
            "language_audio": ["fr", "en"],
            "mood": "suspenseful",
            "duration_max_minutes": 120,
            "similar_to": ["Stranger Things", "Bienvenue à Zombieland"],
          },
          "tags": {"user_id": "U-456", "profile": "adult"},
        },
      },
      "gestion_projet": {
        "summary": "Planification de sprint agile",
        "description": "Assigne des tâches et estime la charge de travail pour un sprint.",
        "value": {
          "message": "Prépare le sprint 24 avec les stories prioritaires",
          "language": "fr",
          "context": {
            "project_id": "PROJ-XYZ",
            "sprint_number": 24,
            "sprint_duration_days": 14,
            "team_capacity_hours": 160,
            "stories": [
              {"id": "ST-101", "title": "Authentification SSO", "points": 5, "priority": "high"},
              {"id": "ST-102", "title": "Dashboard analytics", "points": 8, "priority": "medium"},
              {"id": "ST-103", "title": "Export PDF", "points": 3, "priority": "high"},
            ],
            "velocity_historical": 30,
            "dependencies": ["ST-101 -> ST-102"],
          },
          "tags": {"scrum_master": "jean", "product_owner": "lucie", "sprint_goal": "MVP_release"},
        },
      },
    },
  ),
) -> ProcessResponse:
  """Process and route a natural-language request.

  The endpoint normalizes the input, detects its language when `language` is
  omitted, and routes the request to the best available capability:

  - conversational answers and native date/time, calculator, or conversion tools;
  - Wikipedia for stable knowledge and DuckDuckGo for current information;
  - configured scheduling, weather, radio, podcast, or Zigbee services.

  `context` carries structured data needed by a service, such as an IANA
  timezone, coordinates, temperature unit, or device state. `tags` contains
  caller-defined string metadata and is forwarded where supported.

  A valid request normally returns HTTP 200 even when a selected service needs
  more information or is temporarily unavailable. In that case, `ok` is false,
  `message` is safe to show to the user, and `data.error.type` identifies the
  failure. Schema validation failures return HTTP 422.
  """
  context: AppContext = request.app.state.context

  return await context.orchestrator.process(payload)
