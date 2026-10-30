import pytest

from navi.llm import safety


@pytest.fixture()
def blocked():
    """A filter with harmless dummy blocklist entries (the real blocklist is owner-supplied)."""
    safety.configure(settings=None, blocklist=["zorgblat", "snarf wibble", "മോശം"], allowed_terms=[])
    yield safety._filter
    safety.configure(settings=None, blocklist=[], allowed_terms=[])
    safety._filter.settings = None
