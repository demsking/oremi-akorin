import httpx
import pytest

from oremi_akorin.services.search import SearchService


@pytest.mark.asyncio
async def test_search_returns_a_direct_answer_with_attribution():
  captured = None

  def handler(request):
    nonlocal captured
    captured = request
    return httpx.Response(
      200,
      json={
        "Heading": "Python",
        "AbstractText": "Python is a programming language.",
        "AbstractSource": "Wikipedia",
        "AbstractURL": "https://en.wikipedia.org/wiki/Python_(programming_language)",
        "RelatedTopics": [],
      },
    )

  transport = httpx.MockTransport(handler)

  async with httpx.AsyncClient(transport=transport) as client:
    message, data = await SearchService(client, timeout=3.5).process("Python language", "en", {}, {})

  assert captured is not None
  assert captured.extensions["timeout"]["read"] == 3.5
  assert message == "Python is a programming language."
  assert data == {
    "source": "Wikipedia",
    "url": "https://en.wikipedia.org/wiki/Python_(programming_language)",
    "heading": "Python",
    "results": [],
  }


@pytest.mark.asyncio
async def test_search_flattens_nested_related_topics():
  transport = httpx.MockTransport(
    lambda request: httpx.Response(
      200,
      json={
        "RelatedTopics": [
          {"Name": "group", "Topics": [{"Text": "First useful result", "FirstURL": "https://example.test/1"}]},
          {"Text": "Second result", "FirstURL": "https://example.test/2"},
        ]
      },
    )
  )

  async with httpx.AsyncClient(transport=transport) as client:
    message, data = await SearchService(client).process("something", "en", {}, {})

  assert message == "First useful result"
  assert data["url"] == "https://example.test/1"
  assert data["results"] == [
    {"text": "First useful result", "url": "https://example.test/1"},
    {"text": "Second result", "url": "https://example.test/2"},
  ]
