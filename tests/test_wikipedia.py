import httpx
import pytest

from akorin.core.exceptions import NoResultFound
from akorin.services.wikipedia import USER_AGENT
from akorin.services.wikipedia import WikipediaService


@pytest.mark.asyncio
async def test_wikipedia_returns_localized_article_extract_and_attribution():
  captured = None

  def handler(request: httpx.Request) -> httpx.Response:
    nonlocal captured
    captured = request
    return httpx.Response(
      200,
      json={
        "query": {
          "pages": [
            {
              "title": "Nelson Mandela",
              "extract": "Nelson Mandela était un homme d'État sud-africain.",
              "fullurl": "https://fr.wikipedia.org/wiki/Nelson_Mandela",
            }
          ]
        }
      },
    )

  async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
    service = WikipediaService(client)
    message, data = await service.process("Qui était Nelson Mandela ?", "fr", {}, {})

  assert captured is not None
  assert captured.url.host == "fr.wikipedia.org"
  assert captured.headers["user-agent"] == USER_AGENT
  assert captured.url.params["generator"] == "search"
  assert captured.url.params["gsrsearch"] == "Qui était Nelson Mandela ?"
  assert captured.url.params["exsentences"] == "3"
  assert message == "Nelson Mandela était un homme d'État sud-africain."
  assert data == {
    "source": "Wikipedia",
    "title": "Nelson Mandela",
    "url": "https://fr.wikipedia.org/wiki/Nelson_Mandela",
    "language": "fr",
    "license": "CC BY-SA",
  }


@pytest.mark.asyncio
async def test_wikipedia_includes_request_context_in_search_text():
  captured = None

  def handler(request: httpx.Request) -> httpx.Response:
    nonlocal captured
    captured = request
    return httpx.Response(
      200,
      json={
        "query": {
          "pages": [
            {
              "title": "Python",
              "extract": "Python is a programming language.",
              "fullurl": "https://en.wikipedia.org/wiki/Python_(programming_language)",
            }
          ]
        }
      },
    )

  async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
    service = WikipediaService(client)
    await service.process("Python", "en", {"topic": "programming", "audience": "beginner"}, {})

  assert captured is not None
  assert captured.url.params["gsrsearch"] == 'Python\n\nContext: {"audience":"beginner","topic":"programming"}'


@pytest.mark.asyncio
async def test_wikipedia_signals_when_no_article_matches():
  transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"query": {"pages": []}}))
  async with httpx.AsyncClient(transport=transport) as client:
    service = WikipediaService(client)

    with pytest.raises(NoResultFound):
      await service.process("unknown subject", "en", {}, {})
