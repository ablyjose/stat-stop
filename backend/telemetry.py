"""Shared telemetry validation and delta calculation for the API and importer."""
import numpy as np


def get_lap_telemetry(lap):
    """Use car channels when optional position data cannot be merged."""
    def validate(frame):
        points = [{"Distance": float(distance), "Time": float(elapsed.total_seconds())}
                  for distance, elapsed in zip(frame['Distance'], frame['Time'])]
        calculate_telemetry_delta(points, points)
        return frame

    try:
        return validate(lap.get_telemetry().add_distance())
    except KeyError as error:
        if 'Date' not in str(error):
            raise
    except ValueError:
        # Position interpolation can also introduce invalid distance samples.
        pass
    car = lap.get_car_data(interpolate_edges=True).add_distance()
    # A stationary car can have successive samples at the same distance.
    # Keep the departure time so its stopped time remains in the elapsed trace.
    car = car.loc[car['Distance'].ne(car['Distance'].shift(-1))].copy()
    return validate(car)


def calculate_telemetry_delta(driver1_telemetry, driver2_telemetry):
    """Reproduce FastF1's scaled-distance delta calculation from cached data."""
    def series(telemetry, label):
        if not isinstance(telemetry, list) or len(telemetry) < 2:
            raise ValueError(f"{label} telemetry must contain at least two samples")
        try:
            distances = np.asarray([point["Distance"] for point in telemetry], dtype=float)
            times = np.asarray([point["Time"] for point in telemetry], dtype=float)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{label} telemetry samples require numeric Distance and Time values") from exc
        if not np.isfinite(distances).all() or not np.isfinite(times).all():
            raise ValueError(f"{label} telemetry contains non-finite Distance or Time values")
        if not np.all(np.diff(distances) > 0):
            raise ValueError(f"{label} telemetry Distance values must be strictly increasing")
        if not np.all(np.diff(times) >= 0):
            raise ValueError(f"{label} telemetry Time values must be nondecreasing")
        if distances[-1] <= 0:
            raise ValueError(f"{label} telemetry must cover a positive distance")
        return distances, times

    d1_distances, d1_times = series(driver1_telemetry, "Driver 1")
    d2_distances, d2_times = series(driver2_telemetry, "Driver 2")
    distance_multiplier = d1_distances[-1] / d2_distances[-1]
    scaled_d2_distances = d2_distances * distance_multiplier
    padded_d2_distances = np.concatenate((
        [scaled_d2_distances[0] - (scaled_d2_distances[1] - scaled_d2_distances[0])],
        scaled_d2_distances,
        [scaled_d2_distances[-1] + (scaled_d2_distances[-1] - scaled_d2_distances[-2])],
    ))
    padded_d2_times = np.concatenate((
        [d2_times[0] - (d2_times[1] - d2_times[0])], d2_times,
        [d2_times[-1] + (d2_times[-1] - d2_times[-2])],
    ))
    interpolated_d2_times = np.interp(d1_distances, padded_d2_distances, padded_d2_times)
    return [
        {"Distance": float(distance), "Delta": float(delta)}
        for distance, delta in zip(d1_distances, interpolated_d2_times - d1_times)
    ]

