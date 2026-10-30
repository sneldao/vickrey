# zcashd-wallet-tool (unmodified upstream)

Interactive wallet backup helper shipped inside the compat image for the
operator's own terminal use — the daemon's `walletrequirebackup=1` guard
requires a human-run backup confirmation, and this is the official tool for
it. Run the helper directly in a private terminal.

- Source (byte-for-byte, SHA256-pinned at build):
  `src/rust/bin/wallet_tool.rs` at commit `5c11db4f4fbc0fbd74da77d5e7b2cdb40703390c`
  of `ZcashFoundation/zcashd`, sha256 `7a07032a435c5a05ae352a8fd25e406299f3eb5d2053970655cf09ee057b6719`.
- License: MIT (upstream zcashd).
- The crate here is only the thin standalone package wrapper; dependency
  versions in `Cargo.toml` come from the official fork's `Cargo.lock` and the
  generated `Cargo.lock` is committed so `--locked` builds are reproducible.
- It prints the recovery phrase during the backup challenge. Do not run it
  through an agent or shared log capture.
