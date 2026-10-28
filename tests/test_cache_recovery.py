import io
import json
import math
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from botocore.exceptions import ClientError

from backend import r2_client
from backend.routers import data
from backend.scripts import auto_prepopulate as auto, prepopulate


@pytest.mark.parametrize('payload', [None, {}, {'TotalLaps': 0, 'Drivers': {}},
    {'TotalLaps': 50, 'Drivers': {'NOR': {'Laps': []}}},
    {'TotalLaps': 50, 'Drivers': {'NOR': {'Laps': [{'LapNumber': 1, 'LapTime': math.nan}]}}},
    {'TotalLaps': 50, 'Drivers': {'NOR': {'Laps': [{'LapNumber': 1, 'LapTime': None}]}}}])
def test_invalid_pace_indexes_are_cache_misses(payload):
    assert r2_client.valid_race_pace(payload) is False


@pytest.mark.parametrize('code, missing', [('404', True), ('NoSuchKey', True),
                                        ('AccessDenied', False), ('SlowDown', False)])
def test_head_errors_distinguish_missing_objects_from_unavailable_storage(code, missing):
    client = MagicMock()
    client.head_object.side_effect = ClientError({'Error': {'Code': code}}, 'HeadObject')
    with patch.object(r2_client, 'get_r2_client', return_value=client):
        if missing:
            assert r2_client.check_cache_exists('key') is False
        else:
            with pytest.raises(ClientError):
                r2_client.check_cache_exists('key')


def test_json_upload_sanitizes_nested_nonfinite_values():
    client = MagicMock()
    with patch.object(r2_client, 'get_r2_client', return_value=client):
        assert r2_client.set_json_cache('key', {'values': [math.nan, math.inf, 12.5]})
    assert json.loads(client.put_object.call_args.kwargs['Body']) == {'values': [None, None, 12.5]}


def test_cache_body_is_closed_after_invalid_json():
    client = MagicMock()
    body = io.BytesIO(b'invalid json')
    client.get_object.return_value = {'Body': body}
    with patch.object(r2_client, 'get_r2_client', return_value=client):
        assert r2_client.get_json_cache('key') is None
    assert body.closed


def test_empty_source_returns_503_and_never_writes_empty_timing():
    session = MagicMock()
    session.laps = pd.DataFrame({'LapNumber': [], 'Driver': []})
    with patch.object(data, 'get_json_cache', return_value={'TotalLaps': 0, 'Drivers': {}}), \
         patch.object(data.fastf1, 'get_session', return_value=session), \
         patch.object(data, 'set_json_cache') as upload:
        with pytest.raises(data.HTTPException) as error:
            data.get_race_pace(2026, 'United States Grand Prix', 'R', 'NOR')
    assert error.value.status_code == 503
    upload.assert_not_called()


def test_missing_numbered_lap_returns_404():
    session = MagicMock()
    session.laps.pick_drivers.return_value.pick_laps.return_value.empty = True
    with patch.object(data, 'get_json_cache', return_value=None), \
         patch.object(data.fastf1, 'get_session', return_value=session):
        with pytest.raises(data.HTTPException) as error:
            data.get_telemetry(2026, 'Monaco Grand Prix', 'Q', 'NOR', 'PIA', '99')
    assert error.value.status_code == 404


def test_partial_cache_hit_preserves_available_driver():
    cached = {'Telemetry': [{'Distance': 0., 'Time': 0.}, {'Distance': 100., 'Time': 1.}], 'LapTime': 1.}
    session = MagicMock()
    lap = MagicMock()
    lap.__getitem__.return_value = pd.Timedelta(seconds=1)
    lap.get_telemetry.return_value.add_distance.return_value = pd.DataFrame({
        'Distance': [0., 100.], 'Time': pd.to_timedelta([0, 1], unit='s'),
        'Speed': [100, 100], 'Throttle': [100, 100], 'Brake': [0, 0],
        'RPM': [10000, 10000], 'nGear': [4, 4], 'DRS': [0, 0]})
    session.laps.pick_drivers.return_value.pick_fastest.return_value = lap
    with patch.object(data, 'get_json_cache', side_effect=[cached, None, r2_client.circuit_corners_payload([])]), \
         patch.object(data.fastf1, 'get_session', return_value=session), \
         patch.object(data, 'set_json_cache') as upload:
        result = data.get_telemetry(2026, 'Monaco Grand Prix', 'Q', 'NOR', 'PIA')
    session.laps.pick_drivers.assert_called_once_with('PIA')
    assert upload.call_count == 1
    assert result['Driver1']['Telemetry'] == cached['Telemetry']


def test_prepopulation_normalizes_alias_and_covers_sprint_shootout():
    event = pd.Series({'EventName': 'Belgian Grand Prix', 'Session1': 'Sprint Shootout',
                       'Session2': 'Sprint', 'Session3': 'Qualifying', 'Session4': 'Race'})
    with patch.object(prepopulate.fastf1, 'get_event', return_value=event), \
         patch.object(prepopulate, 'prepopulate_circuit_corners') as corners, \
         patch.object(prepopulate, 'prepopulate_session_race_pace', return_value=True), \
         patch.object(prepopulate, 'prepopulate_session_telemetry', return_value=True) as telemetry:
        assert prepopulate.prepopulate_gp(2023, 'Belgium') is True
    corners.assert_called_once_with(2023, 'Belgian Grand Prix', force=False)
    assert 'SS' in [call.args[2] for call in telemetry.call_args_list]


def test_scheduler_skips_future_and_unknown_race_times(tmp_path):
    schedule = pd.DataFrame([
        {'RoundNumber': 1, 'EventName': 'Past GP', 'Session4': 'Qualifying', 'Session5': 'Race', 'Session5DateUtc': '2026-03-01 14:00'},
        {'RoundNumber': 2, 'EventName': 'Future GP', 'Session5': 'Race', 'Session5DateUtc': '2026-12-01 14:00'},
        {'RoundNumber': 3, 'EventName': 'Unknown GP', 'Session5': 'Race', 'Session5DateUtc': None},
    ])
    with patch.object(auto.fastf1, 'get_event_schedule', return_value=schedule), \
         patch.object(auto, 'check_is_prepopulated', side_effect=[False, True]), \
         patch.object(auto, 'run_prepopulate_with_retries', return_value=True) as run:
        assert auto.run_schedule(2026, csv_path=tmp_path/'status.csv', now='2026-10-27T12:00:00Z')
    assert run.call_count == 1
    assert run.call_args.args[:2] == (2026, 'Past GP')
    rows = pd.read_csv(tmp_path/'status.csv')
    assert list(rows.Status) == ['PREPOPULATED', 'UPCOMING', 'SCHEDULE_UNKNOWN']


def test_scheduler_retries_failures_without_losing_force_flag():
    with patch.object(auto, 'run_prepopulate_gp', side_effect=[False, True]) as run, \
         patch.object(auto.time, 'sleep') as sleep:
        assert auto.run_prepopulate_with_retries(2026, 'Monaco', force=True, attempts=3, retry_delay=1)
    assert run.call_count == 2
    assert all(call.kwargs['force'] for call in run.call_args_list)
    sleep.assert_called_once_with(1)


def test_package_entrypoint_serves_health_route():
    from fastapi.testclient import TestClient
    from backend.main import app
    with TestClient(app) as client:
        response = client.get('/')
    assert response.status_code == 200
    assert response.json()['message'] == 'F1 Analysis API is running'
