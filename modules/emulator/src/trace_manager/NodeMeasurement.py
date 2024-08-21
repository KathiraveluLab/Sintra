from typing import Iterator

from .Measurement import Measurement


class NodeMeasurement:
    def __init__(self, dpid, measurements: list[Measurement]):
        self.source_dpid = dpid
        self.measurement_list: list[Measurement] = measurements
        self.measurement_iterator: Iterator[Measurement] = iter(measurements)

    def __iter__(self):
        self.measurement_iter = 0
        return self

    def __next__(self):
        if self.measurement_iter >= len(self.measurement_list):
            raise StopIteration
        return self.measurement_list[self.measurement_iter]