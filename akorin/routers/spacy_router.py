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

from akorin.core.router import RequestRouter
from akorin.core.router import RouteContext
from akorin.core.router import RouteSpacyDecision
from akorin.core.service import Service

logger = logging.getLogger(__name__)


class SpacyRouter(RequestRouter):
  """Sub-millisecond NLP intent categorization router powered by spaCy."""

  _NLP_PIPELINE: ClassVar[spacy.language.Language | None] = None

  def __init__(self) -> None:
    self._nlp: spacy.language.Language | None = None
    self._phrase_matcher: PhraseMatcher | None = None
    self._token_matcher: Matcher | None = None

    self._initialize_nlp()

  def _initialize_nlp(self) -> None:
    """Initialize spaCy blank French/English language model and matchers."""
    if SpacyRouter._NLP_PIPELINE is None:
      logger.info("Initializing spaCy NLP pipeline for intent classification...")
      SpacyRouter._NLP_PIPELINE = spacy.blank("fr")

    self._nlp = SpacyRouter._NLP_PIPELINE
    self._phrase_matcher = PhraseMatcher(self._nlp.vocab, attr="LOWER")
    self._token_matcher = Matcher(self._nlp.vocab)

    self._build_phrase_patterns()
    self._build_token_patterns()

  def _build_phrase_patterns(self) -> None:
    if self._nlp is None or self._phrase_matcher is None:
      return

    # Category Phrase Patterns
    category_phrases: dict[Service, list[str]] = {
      Service.OREMI_OJO: [
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
      Service.OREMI_ISAKOSO: [
        "allume la lumière",
        "allume les lumières",
        "allume la lampe",
        "éteins la lumière",
        "éteins les lumières",
        "éteins la lampe",
        "eteins la lumiere",
        "eteins les lumieres",
        "eteins la lampe",
        "allume la prise",
        "éteins la prise",
        "ferme les volets",
        "ouvre les volets",
        "active le chauffage",
        "désactive le chauffage",
        "turn on the light",
        "turn on the lights",
        "turn off the light",
        "turn off the lights",
        "turn on the lamp",
        "turn off the lamp",
        "turn on the plug",
        "turn off the plug",
        "set the temperature",
        "close the blinds",
        "open the blinds",
      ],
      Service.OREMI_ISINMI: [
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
      Service.OREMI_REDIYO: [
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
      Service.OREMI_KANSA: [
        "écouter le podcast",
        "ecouter le podcast",
        "dernier épisode",
        "dernier episode",
        "play podcast",
        "listen to podcast",
        "latest episode",
      ],
      Service.CHAT: [
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

    for service, phrases in category_phrases.items():
      docs = [self._nlp.make_doc(phrase) for phrase in phrases]
      self._phrase_matcher.add(service.value, docs)

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

    # Isakoso / Smart Home Token Patterns
    self._token_matcher.add(
      Service.OREMI_ISAKOSO.value,
      [
        [
          {"LOWER": {"IN": ["allume", "allumer", "éteins", "éteindre", "eteins", "eteindre", "ouvre", "ferme", "active"]}},
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
                "volet",
                "volets",
                "thermostat",
                "radiateur",
                "interrupteur",
              ]
            }
          },
        ],
        [
          {"LOWER": "turn"},
          {"LOWER": {"IN": ["on", "off"]}},
          {"OP": "*"},
          {"LOWER": {"IN": ["light", "lights", "lamp", "lamps", "plug", "plugs", "switch", "switches", "blind", "blinds"]}},
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
      service_name = self._nlp.vocab.strings[match_id]
      matched_text = doc[start:end].text

      try:
        service = Service(service_name)
        duration_ms = (perf_counter() - routing_started) * 1000.0

        logger.info(
          "[%s] SpacyRouter decision via phrase match: service=%s matched_phrase=%r duration_ms=%.2f",
          context.request_id,
          service.value,
          matched_text,
          duration_ms,
        )

        return RouteSpacyDecision(service=service, confidence=0.98)
      except ValueError:
        pass

    # 2. Match Token Patterns (Structural Token Pattern Matcher)
    token_matches = self._token_matcher(doc)

    if token_matches:
      match_id, start, end = token_matches[0]
      service_name = self._nlp.vocab.strings[match_id]
      matched_text = doc[start:end].text

      try:
        service = Service(service_name)
        duration_ms = (perf_counter() - routing_started) * 1000.0

        logger.info(
          "[%s] SpacyRouter decision via token match: service=%s matched_tokens=%r duration_ms=%.2f",
          context.request_id,
          service.value,
          matched_text,
          duration_ms,
        )

        return RouteSpacyDecision(service=service, confidence=0.95)
      except ValueError:
        pass

    logger.debug("[%s] SpacyRouter: No matching intent pattern found", context.request_id)

    return None
