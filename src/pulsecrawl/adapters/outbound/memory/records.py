"""Optional bounded-memory fan-out of extracted records."""


class TeeRecordSink:
    def __init__(self, collector, downstream, collect):
        self.collector, self.downstream, self.collect = collector, downstream, collect

    async def emit(self, records):
        if self.collect:
            await self.collector.emit(records)
        if self.downstream is not None:
            await self.downstream.emit(records)
