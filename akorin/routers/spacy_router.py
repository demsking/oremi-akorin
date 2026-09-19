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

import logging
from time import perf_counter
from typing import ClassVar

import spacy
from spacy.matcher import Matcher
from spacy.matcher import PhraseMatcher

from akorin.agents.prompt_selector_agent import SelectedPrompt
from akorin.core.router import RequestRouter
from akorin.core.router import RouteContext
from akorin.core.router import RouteSpacyDecision
from akorin.core.service import Service

logger = logging.getLogger(__name__)


class SpacyRouter(RequestRouter):
  """Sub-millisecond NLP intent categorization & prompt selection router powered by spaCy."""

  _NLP_PIPELINE: ClassVar[spacy.language.Language | None] = None

  def __init__(self) -> None:
    self._nlp: spacy.language.Language | None = None
    self._phrase_matcher: PhraseMatcher | None = None
    self._token_matcher: Matcher | None = None

    self._initialize_nlp()

  def _initialize_nlp(self) -> None:
    """Initialize spaCy blank French/English language model and matchers."""
    if SpacyRouter._NLP_PIPELINE is None:
      logger.info("Initializing spaCy NLP pipeline for intent & prompt classification...")
      SpacyRouter._NLP_PIPELINE = spacy.blank("fr")

    self._nlp = SpacyRouter._NLP_PIPELINE
    self._phrase_matcher = PhraseMatcher(self._nlp.vocab, attr="LOWER")
    self._token_matcher = Matcher(self._nlp.vocab)

    self._build_phrase_patterns()
    self._build_token_patterns()

  def _build_phrase_patterns(self) -> None:
    if self._nlp is None or self._phrase_matcher is None:
      return

    # Category & Prompt-Specific Phrase Patterns
    category_phrases: dict[str, list[str]] = {
      # --- OJO ---
      Service.OREMI_OJO.value: [
        "météo",
        "meteo",
        "quel temps",
        "la météo",
        "température",
        "temperature",
        "est-ce qu'il pleut",
        "va-t-il pleuvoir",
        "y a-t-il du soleil",
        "prévision",
        "prevision",
        "qualité de l'air",
        "qualite de l'air",
        "pollen",
        "weather",
        "what's the weather",
        "weather forecast",
        "is it raining",
        "air quality",
      ],
      # --- ISAKOSO PROMPTS ---
      f"{Service.OREMI_ISAKOSO.value}:turn_on_device": [
        "allume la lumière",
        "allume les lumières",
        "allume la lampe",
        "allume les lampes",
        "allume la prise",
        "turn on the light",
        "turn on the lights",
        "turn on the lamp",
        "turn on the plug",
        "turn on the switch",
      ],
      f"{Service.OREMI_ISAKOSO.value}:turn_off_device": [
        "éteins la lumière",
        "éteins les lumières",
        "éteins la lampe",
        "éteins la prise",
        "eteins la lumiere",
        "eteins les lumieres",
        "eteins la lampe",
        "turn off the light",
        "turn off the lights",
        "turn off the lamp",
        "turn off the plug",
        "turn off the switch",
      ],
      f"{Service.OREMI_ISAKOSO.value}:toggle_device": [
        "bascule la lumière",
        "bascule la prise",
        "toggle the light",
        "toggle the plug",
        "toggle the switch",
      ],
      f"{Service.OREMI_ISAKOSO.value}:set_device_brightness": [
        "mets la luminosité",
        "règle la luminosité",
        "regle la luminosite",
        "ajuste la luminosité",
        "set the brightness",
        "set brightness",
      ],
      f"{Service.OREMI_ISAKOSO.value}:set_device_color": [
        "mets la couleur",
        "change la couleur",
        "règle la couleur",
        "set the color",
        "set color",
      ],
      f"{Service.OREMI_ISAKOSO.value}:summarize_devices": [
        "état des appareils",
        "etat des appareils",
        "résumé des appareils",
        "summarize devices",
        "status of devices",
      ],
      Service.OREMI_ISAKOSO.value: [
        "ferme les volets",
        "ouvre les volets",
        "active le chauffage",
        "désactive le chauffage",
        "close the blinds",
        "open the blinds",
        "set the temperature",
      ],
      # --- ISINMI ---
      Service.OREMI_ISINMI.value: [
        "rappelle-moi",
        "rappelle moi",
        "mets un réveil",
        "mets une alarme",
        "mets un minuteur",
        "mets un timer",
        "remind me",
        "set an alarm",
        "set a timer",
        "set a reminder",
        "wake me up",
      ],
      # --- REDIYO ---
      Service.OREMI_REDIYO.value: [
        "écouter la radio",
        "ecouter la radio",
        "mets la radio",
        "joue la radio",
        "france inter",
        "france info",
        "bbc radio",
        "play radio",
        "listen to radio",
      ],
      # --- KANSA ---
      Service.OREMI_KANSA.value: [
        "écouter le podcast",
        "ecouter le podcast",
        "dernier épisode",
        "dernier episode",
        "play podcast",
        "listen to podcast",
        "latest episode",
      ],
      # --- CHAT ---
      Service.CHAT.value: [
        "quelle heure",
        "quelle heure est-il",
        "il est quelle heure",
        "donne-moi l'heure",
        "donne moi l'heure",
        "quel jour",
        "quelle date",
        "what time is it",
        "what day is it",
        "what is the date",
        "what's the date",
      ],
    }

    for key, phrases in category_phrases.items():
      docs = [self._nlp.make_doc(phrase) for phrase in phrases]
      self._phrase_matcher.add(key, docs)

  def _build_token_patterns(self) -> None:
    if self._nlp is None or self._token_matcher is None:
      return

    # Ojo / Weather Token Patterns
    self._token_matcher.add(
      Service.OREMI_OJO.value,
      [
        [{"LOWER": {"IN": ["météo", "meteo", "weather", "pollen"]}}],
        [
          {"LOWER": {"IN": ["quel", "quelle"]}},
          {"OP": "?"},
          {"LOWER": {"IN": ["temps", "météo", "meteo", "température", "temperature"]}},
        ],
        [
          {"LOWER": {"IN": ["est-ce", "est"]}},
          {"LOWER": "qu'il"},
          {"LOWER": {"IN": ["pleut", "fasse", "fait"]}},
        ],
      ],
    )

    # Isakoso Prompt-Specific Token Patterns
    self._token_matcher.add(
      f"{Service.OREMI_ISAKOSO.value}:turn_on_device",
      [
        [
          {"LOWER": {"IN": ["allume", "allumer"]}},
          {"OP": "*"},
          {
            "LOWER": {
              "IN": [
                "lumière",
                "lumiere",
                "lumieres",
                "lumières",
                "lampe",
                "lampes",
                "prise",
                "prises",
                "interrupteur",
                "switch",
              ]
            }
          },
        ],
        [
          {"LOWER": "turn"},
          {"LOWER": "on"},
          {"OP": "*"},
          {"LOWER": {"IN": ["light", "lights", "lamp", "lamps", "plug", "plugs", "switch", "switches"]}},
        ],
      ],
    )

    self._token_matcher.add(
      f"{Service.OREMI_ISAKOSO.value}:turn_off_device",
      [
        [
          {"LOWER": {"IN": ["éteins", "éteindre", "eteins", "eteindre"]}},
          {"OP": "*"},
          {
            "LOWER": {
              "IN": [
                "lumière",
                "lumiere",
                "lumieres",
                "lumières",
                "lampe",
                "lampes",
                "prise",
                "prises",
                "interrupteur",
                "switch",
              ]
            }
          },
        ],
        [
          {"LOWER": "turn"},
          {"LOWER": "off"},
          {"OP": "*"},
          {"LOWER": {"IN": ["light", "lights", "lamp", "lamps", "plug", "plugs", "switch", "switches"]}},
        ],
      ],
    )

    # Generic Isakoso Token Patterns
    self._token_matcher.add(
      Service.OREMI_ISAKOSO.value,
      [
        [
          {"LOWER": {"IN": ["ouvre", "ferme", "active", "désactive", "desactive"]}},
          {"OP": "*"},
          {"LOWER": {"IN": ["volet", "volets", "thermostat", "radiateur", "chauffage"]}},
        ],
        [
          {"LOWER": "switch"},
          {"LOWER": {"IN": ["on", "off"]}},
          {"OP": "*"},
          {"LOWER": {"IN": ["light", "lights", "lamp", "lamps", "plug", "plugs", "switch", "switches"]}},
        ],
      ],
    )

    # Isinmi / Scheduling Token Patterns
    self._token_matcher.add(
      Service.OREMI_ISINMI.value,
      [
        [
          {
            "LOWER": {
              "IN": [
                "rappelle-moi",
                "rappelle",
                "réveil",
                "reveil",
                "alarme",
                "minuteur",
                "timer",
                "remind",
                "alarm",
              ]
            }
          }
        ],
        [{"LOWER": "set"}, {"OP": "?"}, {"LOWER": {"IN": ["alarm", "timer", "reminder"]}}],
      ],
    )

    # Rediyo / Radio Token Patterns
    self._token_matcher.add(
      Service.OREMI_REDIYO.value,
      [
        [{"LOWER": {"IN": ["radio", "radios"]}}],
        [{"LOWER": {"IN": ["écouter", "ecouter", "joue", "mets", "play"]}}, {"OP": "*"}, {"LOWER": "radio"}],
      ],
    )

    # Kansa / Podcast Token Patterns
    self._token_matcher.add(
      Service.OREMI_KANSA.value,
      [
        [{"LOWER": {"IN": ["podcast", "podcasts"]}}],
        [{"LOWER": {"IN": ["écouter", "ecouter", "joue", "mets", "play"]}}, {"OP": "*"}, {"LOWER": "podcast"}],
      ],
    )

    # Chat / Time Query Token Patterns
    self._token_matcher.add(
      Service.CHAT.value,
      [
        [
          {"LOWER": {"IN": ["quelle", "quel"]}},
          {"LOWER": {"IN": ["heure", "jour", "date"]}},
        ],
        [
          {"LOWER": "heure"},
          {"LOWER": "est-il"},
        ],
        [
          {"LOWER": "what"},
          {"LOWER": {"IN": ["time", "day", "date"]}},
        ],
      ],
    )

  def _resolve_match(self, match_key: str, text: str, context: RouteContext) -> tuple[Service, SelectedPrompt | None] | None:
    parts = match_key.split(":", 1)
    service_str = parts[0]
    prompt_name = parts[1] if len(parts) > 1 else None

    try:
      service = Service(service_str)
    except ValueError:
      return None

    selected_prompt = None

    if prompt_name:
      available_names = {p.name for p in context.all_prompts} if context.all_prompts else set()

      if not available_names or prompt_name in available_names:
        selected_prompt = SelectedPrompt(name=prompt_name, arguments={"command": text})

    if not selected_prompt:
      selected_prompt = self._infer_service_prompt(service, text, context)

    return service, selected_prompt

  def _infer_service_prompt(self, service: Service, text: str, context: RouteContext) -> SelectedPrompt | None:
    if not context.all_prompts:
      return None

    prompt_names = [getattr(prompt, "name", None) for prompt in context.all_prompts if getattr(prompt, "name", None)]

    if not prompt_names:
      return None

    service_prompts = [
      prompt
      for prompt in context.all_prompts
      if getattr(prompt, "name", None)
      and (
        context.prompt_to_service.get(prompt.name) == service
        or (
          not context.prompt_to_service
          and service == Service.OREMI_REDIYO
          and getattr(prompt, "name", None) in {"play_radio", "summarize_directory", "explore_by_genre"}
        )
      )
    ]

    if not service_prompts:
      return None

    normalized_text = text.lower()

    if service == Service.OREMI_REDIYO:
      prompt_keywords = {
        "play_radio": ["play", "listen", "start", "station", "radio", "bbc", "channel", "dance"],
        "summarize_directory": ["directory", "stats", "summary", "categories", "countries", "languages", "tags", "top"],
        "explore_by_genre": ["genre", "tag", "category", "explore", "popular"],
      }

      for prompt_name, keywords in prompt_keywords.items():
        if any(keyword in normalized_text for keyword in keywords):
          if any(getattr(prompt, "name", None) == prompt_name for prompt in service_prompts):
            return SelectedPrompt(name=prompt_name, arguments={"command": text})

      if any(getattr(prompt, "name", None) == "play_radio" for prompt in service_prompts):
        return SelectedPrompt(name="play_radio", arguments={"command": text})

    if len(service_prompts) == 1:
      prompt = service_prompts[0]
      return SelectedPrompt(name=getattr(prompt, "name", None), arguments={"command": text})

    return None

  async def route(self, context: RouteContext) -> RouteSpacyDecision | None:
    if self._nlp is None or self._phrase_matcher is None or self._token_matcher is None:
      return None

    logger.debug("[%s] Evaluating SpacyRouter", context.request_id)
    routing_started = perf_counter()
    text = context.request.message.strip()

    if not text:
      return None

    doc = self._nlp(text)

    # 1. Match Phrase Patterns (Exact / Lowercase Phrase Matcher)
    phrase_matches = self._phrase_matcher(doc)

    if phrase_matches:
      match_id, start, end = phrase_matches[0]
      match_key = self._nlp.vocab.strings[match_id]
      matched_text = doc[start:end].text
      resolved = self._resolve_match(match_key, text, context)

      if resolved:
        service, selected_prompt = resolved
        duration_ms = (perf_counter() - routing_started) * 1000.0

        logger.info(
          "[%s] SpacyRouter decision via phrase match: service=%s prompt=%s matched_phrase=%r duration_ms=%.2f",
          context.request_id,
          service.value,
          selected_prompt.name if selected_prompt else "none",
          matched_text,
          duration_ms,
        )

        return RouteSpacyDecision(service=service, confidence=0.98, selected_prompt=selected_prompt)

    # 2. Match Token Patterns (Structural Token Pattern Matcher)
    token_matches = self._token_matcher(doc)

    if token_matches:
      match_id, start, end = token_matches[0]
      match_key = self._nlp.vocab.strings[match_id]
      matched_text = doc[start:end].text
      resolved = self._resolve_match(match_key, text, context)

      if resolved:
        service, selected_prompt = resolved
        duration_ms = (perf_counter() - routing_started) * 1000.0

        logger.info(
          "[%s] SpacyRouter decision via token match: service=%s prompt=%s matched_tokens=%r duration_ms=%.2f",
          context.request_id,
          service.value,
          selected_prompt.name if selected_prompt else "none",
          matched_text,
          duration_ms,
        )

        return RouteSpacyDecision(service=service, confidence=0.95, selected_prompt=selected_prompt)

    logger.debug("[%s] SpacyRouter: No matching intent pattern found", context.request_id)

    return None
