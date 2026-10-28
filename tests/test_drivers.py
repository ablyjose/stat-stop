"""Driver lookup tests are offline and safe to collect from any working directory."""
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from backend.routers.data import get_drivers


@pytest.mark.parametrize('session_type', ['Q', 'R', 'SQ', 'SS'])
def test_driver_results_use_lightweight_loading(session_type):
    session = MagicMock()
    session.results = pd.DataFrame({'Abbreviation': ['NOR'], 'FullName': ['Lando Norris']})
    with patch('backend.routers.data.fastf1.get_session', return_value=session):
        assert get_drivers(2026, 'Dutch Grand Prix', session_type) == [
            {'Name': 'Lando Norris', 'Driver': 'NOR'}]
    session.load.assert_called_once_with(telemetry=False, weather=False, messages=False, laps=False)
