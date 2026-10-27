# Verifier receipts and selective disclosure (design)

Status: design only. No code. Policy lives in `docs/PRIVACY.md` (Selective
disclosure, Verifier trust); this doc turns it into a concrete shape and lists
the decisions that still need an owner.

## What is being disclosed

An anchor puts only `commitment` on the wire (`docs/ZANCHOR_API.md`). The
commitment is computed in `apps/field/trust.js`:

    commitment = SHA-256( canonical(entry) )

where `canonical` is a sorted-key JSON serialisation. The full sealed entry
(species, location, timestamp, model id, signature, prev link) is held
off-chain, on the device and in the ledger, and is never sent to the verifier.

So a disclosure has exactly two possible payloads, and they differ in what a
recipient can check:

| Option          | Payload                              | Recipient can verify                                                               | Recipient learns                      |
| --------------- | ------------------------------------ | ---------------------------------------------------------------------------------- | ------------------------------------- |
| A. Receipt only | receipt id, txid, height, commitment | the commitment is on chain at that height                                          | that one anchor exists at that height |
| B. Sealed entry | A + full canonical entry             | the entry hashes to the commitment, and so the anchor binds this exact observation | the observation itself                |

Option A is what PRIVACY.md already promises ("exactly one fact per
disclosure"). Option B is needed only when a recipient must check the content,
not just the existence of the anchor. Recommendation: **A by default**, and B
only when the operator explicitly releases a specific entry for a stated
purpose.

## Flow

1. Verifier holds `commitment <-> txid <-> height` in the receipt table. It
   never holds the entry.
2. Operator asks for a disclosure by receipt id, with a purpose string.
3. Verifier appends an audit line (receipt id, UTC time, purpose) to a local
   file that no endpoint exposes.
4. Verifier returns the payload for the chosen option.
5. Recipient checks: for A, the txid is in the chain at the stated height; for
   B, `SHA-256(canonical(entry)) == commitment`, and the commitment matches the
   on-chain anchor.

The viewing key is needed only in mode B, where the memo bytes must be decrypted
to read the commitment back from the transaction. It is held in the verifier
process environment only, decrypted in memory, used, and dropped. It is never
written to the receipt database.

## Constraints from existing policy

- No list endpoint. Receipts are served only by id.
- The receipt table never stores species, area, timestamp, signature or public key.
- Recipient identity is not stored by the service. The operator's records are the operator's policy.

## Open decisions (need an owner)

1. **Which option is the default?** This doc recommends A. Confirm before
   building the endpoint.
2. **Does option B ship at all in the hackathon scope?** It requires the sealed
   entry to leave the device through the operator, which conflicts with
   "the verifier never receives an entry" unless the operator holds it. Likely
   defer to after submission.
3. **Audit log location and retention.** PRIVACY.md says local and append-only.
   Confirm the path and who can read it.

## Not yet verified

- That the node returns enough to check option A without the viewing key. The
  disclosure path for mode A depends on the probe in `services/zanchor/spike/probe7.py`,
  which must run first. Mode B depends on `z_exportviewingkey` / memo decryption,
  which is not exercised anywhere yet.

## Next step

Once the decisions above are answered, implement option A as one endpoint
(`GET /receipts/{id}/disclosure`) with the audit line, and test it against the
mock node. Option B waits for decision 2.
