"""Minimal pack=4 LMU ABI offsets, not an upstream Python implementation.

Source: LMU Support\\SharedMemoryInterface; cross-checked with TinyPedal's
MIT mapping (Tony Whitley 2021; Xiang 2025). See THIRD_PARTY_NOTICES.md.
"""

MAP_NAME = "LMU_Data"
MAP_SIZE = 324820
MAX_VEHICLES = 104
TELEMETRY_OFFSET = 128464
TELEMETRY_RECORDS = TELEMETRY_OFFSET + 4
TELEMETRY_RECORD_SIZE = 1888
SCORING_RECORDS = 1632 + 548 + 12
SCORING_RECORD_SIZE = 584
