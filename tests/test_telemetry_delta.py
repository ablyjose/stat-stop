import math
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from fastapi import HTTPException

from backend.routers.data import calculate_telemetry_delta, get_telemetry


DRIVER1 = [
    {"Distance": 0.0, "Time": 0.0},
    {"Distance": 50.0, "Time": 5.0},
    {"Distance": 100.0, "Time": 10.0},
]
DRIVER2 = [
    {"Distance": 0.0, "Time": 0.0},
    {"Distance": 50.0, "Time": 4.5},
    {"Distance": 100.0, "Time": 9.0},
]


def test_delta_matches_fastf1_compare_minus_reference_convention():
    delta = calculate_telemetry_delta(DRIVER1, DRIVER2)
    assert [point["Distance"] for point in delta] == [0.0, 50.0, 100.0]
    assert [point["Delta"] for point in delta] == [0.0, -0.5, -1.0]

def test_delta_scales_comparison_distance_like_fastf1():
    reference = [{"Distance": 0.0, "Time": 0.0}, {"Distance": 100.0, "Time": 10.0}, {"Distance": 200.0, "Time": 20.0}]
    comparison = [{"Distance": 0.0, "Time": 0.0}, {"Distance": 50.0, "Time": 4.0}, {"Distance": 100.0, "Time": 18.0}]

    delta = calculate_telemetry_delta(reference, comparison)

    assert [point["Delta"] for point in delta] == [0.0, -6.0, -2.0]

def test_delta_equal_laps_is_zero():
    assert all(point["Delta"] == 0.0 for point in calculate_telemetry_delta(DRIVER1, DRIVER1))


@pytest.mark.parametrize("bad_series", [
    [{"Distance": 0.0, "Time": 0.0}],
    [{"Distance": 0.0, "Time": 0.0}, {"Distance": 0.0, "Time": 1.0}],
    [{"Distance": 0.0, "Time": 1.0}, {"Distance": 1.0, "Time": 0.0}],
    [{"Distance": 0.0, "Time": 0.0}, {"Distance": math.nan, "Time": 1.0}],
])
def test_delta_rejects_invalid_samples(bad_series):
    with pytest.raises(ValueError):
        calculate_telemetry_delta(bad_series, DRIVER2)


def test_endpoint_cache_hit_and_miss_return_the_same_delta():
    cache = {}

    def get_cache(key):
        return cache.get(key)

    def set_cache(key, value):
        cache[key] = value
        return True

    d1_frame = pd.DataFrame({
        "Distance": [0.0, 50.0, 100.0], "Speed": [1, 1, 1], "Throttle": [1, 1, 1],
        "Brake": [0, 0, 0], "RPM": [1, 1, 1], "nGear": [1, 1, 1], "DRS": [0, 0, 0],
        "Time": [pd.Timedelta(seconds=0), pd.Timedelta(seconds=5), pd.Timedelta(seconds=10)],
    })
    d2_frame = d1_frame.copy()
    d2_frame["Time"] = [pd.Timedelta(seconds=0), pd.Timedelta(seconds=4.5), pd.Timedelta(seconds=9)]
    lap1, lap2 = MagicMock(), MagicMock()
    lap1.get_telemetry.return_value.add_distance.return_value = d1_frame
    lap2.get_telemetry.return_value.add_distance.return_value = d2_frame
    lap1.__getitem__.return_value = pd.Timedelta(seconds=10)
    lap2.__getitem__.return_value = pd.Timedelta(seconds=9)
    session = MagicMock()
    session.laps.pick_drivers.side_effect = lambda driver: MagicMock(pick_fastest=MagicMock(return_value=lap1 if driver == "VER" else lap2))

    with patch("backend.routers.data.get_json_cache", side_effect=get_cache), \
         patch("backend.routers.data.set_json_cache", side_effect=set_cache), \
         patch("backend.routers.data.fastf1.get_session", return_value=session):
        miss = get_telemetry(2024, "Monaco", "Q", "VER", "HAM")
        hit = get_telemetry(2024, "Monaco", "Q", "VER", "HAM")

    assert miss["Delta"] == hit["Delta"]
    assert miss["DeltaConvention"].startswith("Driver2 elapsed time - Driver1")
    assert miss["DeltaReferenceDriver"] == "VER"


def test_endpoint_invalid_cached_telemetry_returns_actionable_error():
    bad = {"Telemetry": [{"Distance": 0.0, "Time": 0.0}], "LapTime": 1.0}
    with patch("backend.routers.data.get_json_cache", side_effect=[bad, bad]):
        with pytest.raises(HTTPException) as exc_info:
            get_telemetry(2024, "Monaco", "Q", "VER", "HAM")
    assert exc_info.value.status_code == 422
    assert "at least two samples" in exc_info.value.detail


QUALIFYING_FIXTURE = {
    "event": "2024 Monaco Grand Prix Qualifying",
    "driver1": "LEC",
    "driver2": "PIA",
    "driver1_lap_time": 70.270,
    "driver2_lap_time": 70.424,
    "driver1_telemetry": [{"Distance": 0.0, "Time": 0.0}, {"Distance": 100.0, "Time": 35.0}, {"Distance": 200.0, "Time": 70.270}],
    "driver2_telemetry": [{"Distance": 0.0, "Time": 0.0}, {"Distance": 100.0, "Time": 35.1}, {"Distance": 200.0, "Time": 70.424}],
}


def test_qualifying_fixture_final_delta_agrees_with_official_lap_times():
    fixture = QUALIFYING_FIXTURE
    delta = calculate_telemetry_delta(fixture["driver1_telemetry"], fixture["driver2_telemetry"])
    expected_delta = fixture["driver2_lap_time"] - fixture["driver1_lap_time"]

    assert delta[-1]["Delta"] > 0  # Driver 1's official lap is faster.
    assert math.isclose(delta[-1]["Delta"], expected_delta, abs_tol=0.01)