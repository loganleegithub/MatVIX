# MatVIX local data

The runtime tables and vendor files in this directory are local artifacts and
are intentionally excluded from Git.  The accepted real-data snapshot was
downloaded on 2026-08-20 from the official Cboe index and CFE historical-data
endpoints.

Accepted input coverage:

- Cboe VIX, VIX9D, VIX3M, VIX6M, VVIX, SKEW, and SPX histories;
- 172 standard-monthly CFE VX contract files, January 2013 through April 2027;
- complete positive-settlement F1-F6 curves from 2013-05-20 through
  2026-08-18 (3,332 XNYS sessions);
- four source SKEW gaps are preserved as missing: 2017-09-14, 2018-12-03,
  2019-07-05, and 2024-11-29;
- 852 official CFE `Settle=0` rows are invalid observations and must not be
  forward-filled or replaced with `Close`.

The byte-level inventory and 183 accepted checksums are kept locally at:

- `data/raw/vendor/audit/inventory.json`
- `data/raw/vendor/audit/SHA256SUMS.txt`

Run the checksum command from `data/raw/vendor` because manifest paths are
relative:

```bash
shasum -a 256 -c audit/SHA256SUMS.txt
```

Official public download endpoints do not by themselves grant unrestricted
commercial redistribution rights.  Keep raw files local and confirm the
project owner's Cboe data licence before professional or commercial use.
