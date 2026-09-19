# Shared-memory ABI sources

The project-owned raw reader in `src/lmu_corner_cues/lmu.py` and offset constants
in `_lmu_layout.py` use the pack=4 `SharedMemoryObjectOut` layout from LMU's
`Support\SharedMemoryInterface`. The offsets were cross-checked against
TinyPedal's MIT-licensed mapping (copyright Tony Whitley 2021; Xiang 2025).
No upstream Python implementation is copied or imported, and no external
shared-memory package is required at runtime.

Compatibility is limited to the 324820-byte `LMU_Data` layout. The reader checks
buffer length, player availability/index, identifiers and finite numeric values.
These checks are not version detection: a future ABI with the same size but
changed field offsets may not be detected. Reading a copy of the live map does
not provide an atomic snapshot; LMU may update it during the copy. Live Windows
validation remains necessary for supported game builds.
