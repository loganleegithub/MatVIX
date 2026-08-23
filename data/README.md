# MatVIX local data

The runtime tables, vendor files and prospective observations in this directory
are local artifacts unless explicitly tracked. The accepted source generations
come from official Cboe index and CFE historical-data endpoints.

Accepted input coverage:

- Cboe VIX, VIX9D, VIX3M, VIX6M, VVIX, SKEW, and SPX histories;
- 172 standard-monthly CFE VX contract files, January 2013 through April 2027;
- normalized V3 state history from 2013-05-20 through 2026-08-20 (3,334 XNYS
  sessions: 2,803 `OK`, 531 `PARTIAL`);
- four source SKEW gaps are preserved as missing: 2017-09-14, 2018-12-03,
  2019-07-05, and 2024-11-29;
- 852 official CFE `Settle=0` rows are invalid observations and must not be
  forward-filled or replaced with `Close`.

The original authorized vendor bundle has a byte-level inventory and 183
accepted checksums. The accepted 2026-08-19/20 live generation remains local;
`configs/release_live_generation.json` records its nine file identities and original
ingestion timestamps without redistributing the files. `matvix import-release-generation`
verifies and admits that generation through the same source-identity and point-in-time
rules.

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
