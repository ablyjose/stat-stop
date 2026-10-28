from unittest.mock import MagicMock
import pandas as pd
import pytest
from backend.telemetry import get_lap_telemetry


def frame(distances):
    return pd.DataFrame({'Distance': distances,
                         'Time': pd.to_timedelta(range(len(distances)), unit='s')})


def test_missing_position_dates_uses_car_data():
    lap = MagicMock()
    lap.get_telemetry.side_effect = KeyError("None of ['Date'] are in the columns")
    expected = frame([0., 10., 20.])
    lap.get_car_data.return_value.add_distance.return_value = expected
    pd.testing.assert_frame_equal(get_lap_telemetry(lap), expected)
    lap.get_car_data.assert_called_once_with(interpolate_edges=True)


def test_invalid_merged_distance_uses_car_data():
    lap = MagicMock()
    lap.get_telemetry.return_value.add_distance.return_value = frame([0., 10., 10.])
    expected = frame([0., 10., 20.])
    lap.get_car_data.return_value.add_distance.return_value = expected
    pd.testing.assert_frame_equal(get_lap_telemetry(lap), expected)


def test_invalid_car_data_still_fails():
    lap = MagicMock()
    lap.get_telemetry.side_effect = KeyError('Date')
    lap.get_car_data.return_value.add_distance.return_value = frame([0., 0.])
    with pytest.raises(ValueError):
        get_lap_telemetry(lap)


def test_stationary_samples_preserve_departure_time():
    lap = MagicMock()
    lap.get_telemetry.side_effect = KeyError('Date')
    lap.get_car_data.return_value.add_distance.return_value = frame([0., 10., 10., 20.])
    result = get_lap_telemetry(lap)
    assert result['Distance'].tolist() == [0., 10., 20.]
    assert result['Time'].dt.total_seconds().tolist() == [0., 2., 3.]
