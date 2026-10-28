import importlib.util
from pathlib import Path
from unittest.mock import patch, MagicMock
import numpy as np
import pandas as pd

spec = importlib.util.spec_from_file_location(
    "prepopulate_module",
    Path(__file__).resolve().parents[1] / "backend" / "scripts" / "prepopulate.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_extract_corners_from_circuit_info_handles_missing_distance():
    class FakeCorner:
        def __init__(self, number, distance, letter):
            self._values = {"Number": number, "Distance": distance, "Letter": letter}

        def __getitem__(self, key):
            return self._values[key]

    class FakeCorners:
        def iterrows(self):
            return iter([
                (0, FakeCorner(1, 100.0, "A")),
                (1, FakeCorner(2, float("nan"), "B")),
            ])

    class FakeCircuitInfo:
        def __init__(self):
            self.corners = FakeCorners()

    corners = module.extract_corners_from_circuit_info(FakeCircuitInfo())
    assert corners == [
        {"Number": 1, "Distance": 100.0, "Letter": "A"},
    ]


def test_prepopulate_gp_calls_correct_sessions():
    with patch.object(module, "prepopulate_circuit_corners") as mock_corners, \
         patch.object(module, "prepopulate_session_race_pace") as mock_race_pace, \
         patch.object(module, "prepopulate_session_telemetry") as mock_telemetry, \
         patch.object(module.fastf1, "get_event", return_value=pd.Series({
             "Session1": "Practice 1",
             "Session2": "Sprint Qualifying",
             "Session3": "Sprint",
             "Session4": "Qualifying",
             "Session5": "Race",
         })):
         
        module.prepopulate_gp(2024, "Monaco")
        
        mock_corners.assert_called_once_with(2024, "Monaco", force=False)
        
        # Race pace only for S and R
        race_pace_calls = [c.args[2] for c in mock_race_pace.call_args_list]
        assert sorted(race_pace_calls) == sorted(['S', 'R'])
        
        # Telemetry for SQ, S, Q, R
        telemetry_calls = [c.args[2] for c in mock_telemetry.call_args_list]
        assert sorted(telemetry_calls) == sorted(['SQ', 'S', 'Q', 'R'])


def test_prepopulate_gp_skips_sessions_not_in_event():
    event = pd.Series({
        "Session1": "Practice 1",
        "Session2": "Practice 2",
        "Session3": "Practice 3",
        "Session4": "Qualifying",
        "Session5": "Race",
    })

    with patch.object(module, "prepopulate_circuit_corners"), \
         patch.object(module, "prepopulate_session_race_pace") as mock_race_pace, \
         patch.object(module, "prepopulate_session_telemetry") as mock_telemetry, \
         patch.object(module.fastf1, "get_event", return_value=event):
        module.prepopulate_gp(2024, "Abu Dhabi Grand Prix")

    assert [call.args[2] for call in mock_race_pace.call_args_list] == ["R"]
    assert [call.args[2] for call in mock_telemetry.call_args_list] == ["R", "Q"]


def test_pick_telemetry_lap_falls_back_when_driver_has_no_fastest_lap():
    fallback_lap = MagicMock()
    driver_laps = MagicMock()
    driver_laps.empty = False
    driver_laps.pick_fastest.return_value = None
    driver_laps.iloc.__getitem__.return_value = fallback_lap

    assert module.pick_telemetry_lap(driver_laps) is fallback_lap


def test_extract_lap_time_handles_one_row_laps_with_nat():
    retired_driver_laps = pd.DataFrame({"LapTime": [pd.NaT]})

    assert module.extract_lap_time(retired_driver_laps) is None


def test_extract_lap_time_converts_timedelta_to_seconds():
    lap = pd.Series({"LapTime": pd.Timedelta(seconds=90.125)})

    assert module.extract_lap_time(lap) == 90.125


def test_drivers_loads_sprint_qualifying_results_without_telemetry():
    from backend.routers.data import get_drivers

    session = MagicMock()
    session.results = pd.DataFrame({"Abbreviation": ["NOR"], "FullName": ["Lando Norris"]})

    with patch("backend.routers.data.fastf1.get_session", return_value=session):
        assert get_drivers(2024, "Chinese Grand Prix", "SQ") == [{"Name": "Lando Norris", "Driver": "NOR"}]

    session.load.assert_called_once_with(telemetry=False, weather=False, messages=False, laps=False)


def test_drivers_keeps_lightweight_load_for_other_sessions():
    from backend.routers.data import get_drivers

    session = MagicMock()
    session.results = pd.DataFrame({"Abbreviation": ["VER"], "FullName": ["Max Verstappen"]})

    with patch("backend.routers.data.fastf1.get_session", return_value=session):
        assert get_drivers(2024, "Chinese Grand Prix", "Q") == [{"Name": "Max Verstappen", "Driver": "VER"}]

    session.load.assert_called_once_with(telemetry=False, weather=False, messages=False, laps=False)

def test_telemetry_cache_hit_reads_circuit_corners():
    from backend.routers.data import get_telemetry
    
    # Mock get_json_cache to return telemetry data for data1, data2, and corners under the circuit key
    def mock_get_json_cache(key):
        if "telemetry" in key and "VER" in key:
            return {"Telemetry": [{"Distance": 0.0, "Time": 0.0}, {"Distance": 100.0, "Time": 80.0}], "LapTime": 80.0}
        if "telemetry" in key and "HAM" in key:
            return {"Telemetry": [{"Distance": 0.0, "Time": 0.1}, {"Distance": 100.0, "Time": 80.1}], "LapTime": 80.1}
        if "circuit/2024/Monaco/corners.json" in key:
            return [{"Number": 1, "Distance": 50.0, "Letter": ""}]
        return None

    with patch("backend.routers.data.get_json_cache", side_effect=mock_get_json_cache) as mock_get:
        res = get_telemetry(year=2024, gp="Monaco", session="R", driver1="VER", driver2="HAM")
        assert res["Corners"] == [{"Number": 1, "Distance": 50.0, "Letter": ""}]
        # Assert it fetched from the circuit key and NOT the timing key
        called_keys = [call.args[0] for call in mock_get.call_args_list]
        assert "circuit/2024/Monaco/corners.json" in called_keys
        assert not any("timing" in k and "laps.json" in k for k in called_keys)


def test_telemetry_cache_hit_fallback_computes_and_caches_corners():
    from backend.routers.data import get_telemetry

    # Mock data1 and data2, but return None for circuit corners to trigger fallback
    def mock_get_json_cache(key):
        if "telemetry" in key and "VER" in key:
            return {"Telemetry": [{"Distance": 0.0, "Time": 0.0}, {"Distance": 100.0, "Time": 80.0}], "LapTime": 80.0}
        if "telemetry" in key and "HAM" in key:
            return {"Telemetry": [{"Distance": 0.0, "Time": 0.1}, {"Distance": 100.0, "Time": 80.1}], "LapTime": 80.1}
        return None

    fake_corners = [{"Number": 1, "Distance": 123.4, "Letter": ""}]

    with patch("backend.routers.data.get_json_cache", side_effect=mock_get_json_cache), \
         patch("backend.routers.data.fastf1.get_session") as mock_get_session, \
         patch("backend.routers.data.get_safe_circuit_info") as mock_get_safe_circuit, \
         patch("backend.routers.data.extract_corners_from_circuit_info", return_value=fake_corners), \
         patch("backend.routers.data.set_json_cache") as mock_set:
        
        mock_sess = MagicMock()
        mock_get_session.return_value = mock_sess
        
        res = get_telemetry(year=2024, gp="Monaco", session="R", driver1="VER", driver2="HAM")
        
        assert res["Corners"] == fake_corners
        mock_set.assert_called_with("circuit/2024/Monaco/corners.json", fake_corners)


def test_telemetry_cache_miss_caches_corners_to_circuit_key():
    from backend.routers.data import get_telemetry

    fake_corners = [{"Number": 1, "Distance": 456.7, "Letter": ""}]
    tel_data = {
        "Distance": [0.0, 100.0], "Speed": [100.0, 100.0], "Throttle": [100.0, 100.0],
        "Brake": [0.0, 0.0], "RPM": [10000.0, 10000.0], "nGear": [4, 4], "DRS": [0, 0],
        "Time": [pd.Timedelta(seconds=0.0), pd.Timedelta(seconds=90.0)],
    }
    mock_lap = MagicMock()
    mock_lap.get_telemetry.return_value.add_distance.return_value = pd.DataFrame(tel_data)
    mock_lap.__getitem__.side_effect = lambda key: pd.Timedelta(seconds=90.0) if key == "LapTime" else None
    mock_session = MagicMock()
    mock_session.laps.pick_drivers.return_value.pick_fastest.return_value = mock_lap

    with patch("backend.routers.data.get_json_cache", return_value=None), \
         patch("backend.routers.data.fastf1.get_session", return_value=mock_session), \
         patch("backend.routers.data.extract_corners_from_circuit_info", return_value=fake_corners), \
         patch("backend.routers.data.set_json_cache") as mock_set:
        result = get_telemetry(year=2024, gp="Monaco", session="R", driver1="VER", driver2="HAM")

    assert result["Corners"] == fake_corners
    mock_set.assert_any_call("circuit/2024/Monaco/corners.json", fake_corners)
    assert all("timing" not in call.args[0] for call in mock_set.call_args_list)
