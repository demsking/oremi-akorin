from akorin.core.constants import Language
from akorin.utils.language import detect_language


def test_detects_supported_languages():
  assert detect_language("Quel temps fera-t-il demain à Paris ?") == Language.FR
  assert detect_language("What will the weather be tomorrow?") == Language.EN
