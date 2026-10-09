# Frozen v11 worker fixture

The archive contains the original `src/` tree and snapshot manifest extracted from
`benchmarks/urgent-blocking-v12/baseline-snapshot.zip`, without regenerating source
from the current checkout. The source follows this repository's MIT license.

- Archive SHA-256: `ae96af77690c34c67c0d05895f5a73d682d20ed918364451cb6a277a50907c54`
- Original source fingerprint: `0fc39f1dcf2ab652c4c218061760f9301b2b003b29f588c84c346b2d194aa8d0`

Tests extract it into a temporary directory and check the original source
fingerprint before exercising an isolated historical policy. No fixed `/tmp`
checkout or separately installed snapshot is needed. Retain the archive unchanged;
a new historical baseline should use a new versioned fixture.
