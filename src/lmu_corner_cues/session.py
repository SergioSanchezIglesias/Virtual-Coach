"""Read-only session inspection; no audio or persistence."""

from .runtime import _closing_reader


def describe(sample):
    return (f"Circuit: {sample.track}\nVehicle: {sample.vehicle}\n"
            f"Class: {sample.vehicle_class}\nLap: {sample.lap}\n"
            f"Lap distance: {sample.distance:.2f} m")


def probe(reader, *, report=print):
    with _closing_reader(reader):
        reader.connect()
        sample = reader.read()
        report(describe(sample))
        return sample
