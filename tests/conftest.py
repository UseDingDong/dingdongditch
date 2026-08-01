from __future__ import annotations

import pytest

from tests.fixtures.local_test_app.server import start_fixture_server


@pytest.fixture(scope="session")
def fixture_url():
    server, url = start_fixture_server()
    yield url
    server.shutdown()
