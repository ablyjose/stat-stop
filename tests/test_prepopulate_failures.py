import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch
import time

import pandas as pd
import pytest

from backend.r2_client import valid_race_pace, read_circuit_corners
from backend.routers import data


def load_script(name):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parents[1] / 'backend' / 'scripts' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepopulate = load_script('prepopulate')
auto = load_script('auto_prepopulate')


def test_empty_pace_cache_is_repaired_and_empty_source_is_not_uploaded():
    session = MagicMock()
    session.laps = pd.DataFrame({'LapNumber': [], 'Driver': []})
    with patch.object(prepopulate, 'get_json_cache', return_value={'TotalLaps': 0, 'Drivers': {}}), \
         patch.object(prepopulate.fastf1, 'get_session', return_value=session), \
         patch.object(prepopulate, 'set_json_cache') as save:
        assert prepopulate.prepopulate_session_race_pace(2026, 'United States Grand Prix', 'R') is False
    save.assert_not_called()


def test_failed_driver_upload_does_not_publish_completion_marker():
    session = MagicMock()
    session.laps.empty = False
    session.laps.__getitem__.return_value = pd.Series(['NOR'])
    session.laps.pick_drivers.return_value.empty = False
    lap = MagicMock()
    lap.get_telemetry.return_value.add_distance.return_value = pd.DataFrame({
        'Distance': [0., 10.], 'Speed': [100., 100.], 'Throttle': [100., 100.],
        'Brake': [0., 0.], 'RPM': [10000., 10000.], 'nGear': [4, 4], 'DRS': [0, 0],
        'Time': pd.to_timedelta([0, 1], unit='s'),
    })
    with patch.object(prepopulate, 'check_cache_exists', return_value=False), \
         patch.object(prepopulate.fastf1, 'get_session', return_value=session), \
         patch.object(prepopulate, 'pick_driver_fastest_lap', return_value=lap), \
         patch.object(prepopulate, 'extract_lap_time', return_value=90.), \
         patch.object(prepopulate, 'set_json_cache', return_value=False) as save:
        assert prepopulate.prepopulate_session_telemetry(2026, 'Spanish Grand Prix', 'Q') is False
    assert len(save.call_args_list) == 1
    assert '_complete' not in save.call_args.args[0]


def test_upload_failure_raises():
    with patch.object(prepopulate, 'set_json_cache', return_value=False):
        with pytest.raises(RuntimeError, match='R2 upload failed'):
            prepopulate.save_cache('timing/test', {})


def test_scheduler_accepts_existing_race_without_new_telemetry_markers():
    with patch.object(auto, 'check_cache_exists', side_effect=lambda key: key == 'timing/2026/Spanish Grand Prix/R/laps.json'):
        assert auto.check_is_prepopulated(2026, 'Spanish Grand Prix', ['R', 'Q']) is True


def test_legacy_completion_marker_is_not_trusted():
    with patch.object(prepopulate, 'check_cache_exists', side_effect=lambda key: '_complete-v1' in key), \
         patch.object(prepopulate.fastf1, 'get_session', side_effect=RuntimeError('source unavailable')):
        assert prepopulate.prepopulate_session_telemetry(2026, 'Spain', 'Q') is False


def test_manual_import_propagates_failure_to_exit_status():
    with patch('sys.argv', ['auto_prepopulate.py', '--gp', 'United States Grand Prix']), \
         patch.object(auto, 'check_cache_exists', return_value=False), \
         patch.object(auto, 'run_prepopulate_with_retries', return_value=False):
        assert auto.main() == 1


def test_child_output_is_logged_and_force_is_forwarded(capsys):
    child = MagicMock()
    child.stdout = iter(['source authentication failed\n'])
    child.wait.return_value = 1
    context = MagicMock()
    context.__enter__.return_value = child
    with patch.object(auto.subprocess, 'Popen', return_value=context) as spawn:
        assert auto.run_prepopulate_gp(2026, 'United States Grand Prix', force=True) is False
    assert '--force' in spawn.call_args.args[0]
    assert 'source authentication failed' in capsys.readouterr().out


def test_missing_corner_map_cache_expires():
    assert read_circuit_corners({'Corners': [], 'RetryAfter': time.time() + 60}) == []
    assert read_circuit_corners({'Corners': [], 'RetryAfter': 1}) is None


def test_cached_telemetry_with_unavailable_map_never_loads_fastf1():
    telemetry = {'Telemetry': [{'Distance': 0., 'Time': 0.}, {'Distance': 100., 'Time': 1.}], 'LapTime': 1.}
    def cache(key):
        if key.startswith('circuit/'):
            return {'Corners': [], 'RetryAfter': time.time() + 60}
        return telemetry
    with patch.object(data, 'get_json_cache', side_effect=cache), \
         patch.object(data.fastf1, 'get_session') as load:
        response = data.get_telemetry(2026, 'Spanish Grand Prix', 'Q', 'RUS', 'ANT')
    assert response['Corners'] == []
    assert len(response['Delta']) == 2
    load.assert_not_called()


def test_driver_without_timed_lap_has_clear_404():
    session = MagicMock()
    session.laps.pick_drivers.return_value.pick_fastest.return_value = None
    with patch.object(data, 'get_json_cache', return_value=None), \
         patch.object(data.fastf1, 'get_session', return_value=session):
        with pytest.raises(data.HTTPException) as error:
            data.get_telemetry(2026, 'Spanish Grand Prix', 'Q', 'BEA', 'NOR')
    assert error.value.status_code == 404
    assert 'No timed lap' in error.value.detail
