# Disclosure — implemented contract (2026-10-30)

_Historical note: this file began as a pre-implementation design. It now
describes the implemented shape — built and browser-tested, but not yet
deployed. Options not built are marked at the end._

A disclosure is a file the record's owner chooses to share. The owner clicks
"Share this record", sees the exact entry including its recorded coordinates
in a preview, enters a purpose, clicks "Download disclosure", and moves the
file by hand — it is never uploaded. The only request that leaves the device
carries the receipt id and that purpose.

## The two halves

1. **Local verification (the file).** `apps/field/disclosure.js` builds a
   `vickrey.disclosure/1` bundle: one sealed entry (including the exact
   recorded coordinates — disclosures deliberately reveal what the anchor
   hides), the device public key (SPKI), the service's public receipt, and
   its verification response. A recipient re-checks, entirely locally, that
   the entry recomputes to its commitment and that the signature verifies
   under the bundled key. One verified entry proves its own seal — it does
   not establish the sender's whole journal chain, the observer's identity,
   or the capture time.
2. **Service check (the memo).** `POST /receipts/{id}/disclosure` validates a
   caller-supplied purpose (1–200 chars), runs a fresh verification, refuses
   unless the memo proof verifies, and writes one append-only row to the
   `disclosure_audit` SQLite table (receipt id, UTC time, purpose — no read
   endpoint). The recipient can also re-run `GET /receipts/{id}/verify`
   against a configured anchor service and compare every binding field.

## Trust limits, stated plainly

- The memo is read by the **service wallet** (`z_viewtransaction`) — a
  service-held check, not independent verification.
- The **receipt id is a bearer capability**: whoever holds it can ask for
  verification and disclosure. The audit names a stated purpose, not a
  verified recipient, and a downloaded file cannot be cryptographically
  revoked.
- **No private keys are disclosed**: no Zcash viewing or spending keys, no
  account keys — no endpoint exports them. The file does include the device's
  **public** key, needed for the recipient's local signature check.
- The service sees only the receipt id and the purpose; the record's
  contents stay in the bundle the user moves by hand.
- The signature verifies the signed bytes under the included device key; it
  is not an identity assertion.

## Deferred from the original design

- Option A-vs-B payloads: the file always carries the sealed entry (option B)
  plus the receipt — a receipt-only file would prove existence but disclose
  nothing checkable about content. In mode A, a receipt alone also cannot
  establish chronology against the entry: its binding is verifier-held with
  no memo proof.
- Recipient identity policy remains the operator's, not the protocol's.

Tests: `apps/field/disclosure.test.mjs` (local verification, tamper, embedded
verification never trusted as fresh proof) and
`services/zanchor/tests/test_contract.py` (disclosure 409/404, audit write
only on success). 2026-10-30.
