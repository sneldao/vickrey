# QIE hackathon submission package — Reality Receipts

Checkpoint: 2026-11-25. This file is the working submission checklist for the
QIE Mainnet Hackathon 3.0 deadline on 2026-11-30 at 23:59 CET.

## Project statement

Reality Receipts is an agent-initiated physical-world verification loop. The
agent first checks remote context. When that context is insufficient, it funds
a bounded public-safe field task, receives only a sealed-record commitment and
public metadata, applies an explicit verifier policy, and settles the bounty on
QIE. The public receipt links the criteria hash, evidence commitment, verdict
and chain transactions without publishing the raw observation.

Primary track: AI + Autonomous Agents. Secondary fit: Commerce & Real World.

## Live testnet demo

- Demo: <https://vickrey.144.202.117.160.sslip.io/receipts/>
- Network: QIE testnet, chain ID 1983 (`0x7bf`)
- Settlement token: test QIE; `real_funds=false`; no economic value
- Escrow contract, source verified on the explorer: [`0xb5BAEF1117B00D1B230Bf806EBFb3FEe5F7c96Ee`](https://testnet.qie.digital/address/0xb5BAEF1117B00D1B230Bf806EBFb3FEe5F7c96Ee)
- Contract deployment transaction: [`0x72c82e326b1aa9c9e5e855e14530e43585497338234cb61d078be65d6ff659fe`](https://testnet.qie.digital/tx/0x72c82e326b1aa9c9e5e855e14530e43585497338234cb61d078be65d6ff659fe)
- Operator/sponsor demo wallet: `0xC40433804A5A5b61610a7b8c55749F41Bc1aBA86`
- Observer demo wallet: `0xC038De41A383fF37b85a512930654a3C68CC2A7c`

## Public end-to-end smoke run, 2026-11-25

Challenge `e9365963-b3c1-44ec-8063-22c0b83f61bf` completed through the public
browser demo. The receipt is available from the demo lookup by challenge ID.

1. Challenge escrow created, 0.001 test QIE:
   [`0x5e7dfdfae410725e29ca366adf168417e522234163e16db46a6cf51dcb89595a`](https://testnet.qie.digital/tx/0x5e7dfdfae410725e29ca366adf168417e522234163e16db46a6cf51dcb89595a)
2. Sealed-evidence commitment submitted for the observer:
   [`0x7f44071a759cfc2387724b716b53d9eee5daf4a0b7afa7906be69f9ee2bcb260`](https://testnet.qie.digital/tx/0x7f44071a759cfc2387724b716b53d9eee5daf4a0b7afa7906be69f9ee2bcb260)
3. Verdict resolution paid the observer 0.001 test QIE:
   [`0x230e79a3d873694cf00ca54bacb3e5220cc35e911eed35b35507bf8ec8e9ae6c`](https://testnet.qie.digital/tx/0x230e79a3d873694cf00ca54bacb3e5220cc35e911eed35b35507bf8ec8e9ae6c)

The browser smoke run verified that the public page loads the same-origin API,
uses the deterministic field-path demo provider, creates exactly
1,000,000,000,000,000 wei, displays the public receipt, and renders all three
transaction explorer links.

## Implemented hackathon slice

- `services/receipts/contracts/src/RealityReceiptsEscrow.sol` — minimal native
  QIE escrow: fixed bounty, criteria hash, expiry, one evidence commitment,
  operator resolution, payout/refund, expired-unresolved refund path.
- `services/receipts/app/qie.py` — web3.py settlement adapter. It creates the
  escrow transaction, relays observer evidence with `submitEvidenceFor`, resolves
  accepted/rejected verdicts, records mined transaction metadata, and refuses
  mainnet unless `RECEIPTS_QIE_MAINNET_ACK=I_APPROVE_REAL_QIE_MAINNET_FUNDS`.
- `services/receipts/app/db.py` — schema v3, including immutable `chain_events`.
- `apps/receipts` — one-claim browser workflow, public receipt lookup/share
  view, network-aware settlement labels and explorer links.
- `docker-compose.demo.yml` and `services/demo/nginx.conf` — same-origin public
  demo deployment with allowlisted `/healthz` and `/v1/` proxy routes.

## Verification evidence

- Receipts backend: 53 pytest tests passed locally.
- Receipts browser core: 12 Node tests passed locally.
- Escrow contract: Forge test suite passed locally.
- Public deployment health: `mode=demo`,
  `remote_evidence_provider=deterministic_demo_field_path`,
  `settlement_adapter=qie_reality_receipts_escrow`,
  `settlement_network=qie_testnet`, `real_funds=false`.
- Public browser smoke: completed end-to-end with the three transactions above.
- Explorer verification: `RealityReceiptsEscrow` source verification passed on the QIE testnet explorer.

## Honest limitations to disclose

- The remote-evidence provider is synthetic deterministic context, not a live
  satellite, sensor or web-evidence provider. The public demo uses
  `deterministic_demo_field_path` so judges can reliably reach the field-evidence
  path; it always returns `insufficient`.
- The service stores a commitment and bounded public metadata, not the raw
  observation. It does not verify the commitment against raw bytes.
- The verifier is an explicit local demo policy using a documented demo key. It
  is not independent adjudication.
- QIE resolution is operator-controlled in this MVP. The contract moves escrow;
  it does not decide truth.
- The observer payout address is authenticated through service bearer
  configuration and relayed by the operator. Direct observer wallet submission
  exists in the contract but is not the browser demo path.
- Non-terminal verdicts do not close escrow. Unresolved escrow is recoverable
  only through the contract expiry/refund path.
- The public demo uses documented demo credentials intentionally. They are not
  production credentials, and the service remains in demo mode.
- QIE testnet coins have no economic value. No mainnet funds have been used.

## Prior-work disclosure

The sealed field-record primitive, local Ed25519 journal, backup/recovery work,
Zcash anchoring exploration and earlier evidence surfaces predate this hackathon
slice. The net-new QIE work is the Reality Receipts claim workflow, escrow
contract, backend QIE settlement integration, chain-event receipt model,
network-aware browser receipt surface, deployment and public testnet evidence.

## Remaining submission gates

1. **Mainnet decision — blocker.** The official page says “Mainnet only.” The
   current demo is testnet-only and the deployment path intentionally refuses
   real mainnet funds without explicit operator approval. A fresh mainnet-only
   operator address has been generated outside the repo:
   `0xb96232679f3688F7e3450Ac34f3e2C456F50B3DA` (balance currently zero). It
   needs a small amount of real QIE before deployment. Do not reuse testnet keys
   on mainnet. Mainnet is chain ID 1990 (`0x7c6`), RPC
   `https://rpc1mainnet.qie.digital/`, explorer <https://mainnet.qie.digital/>.
   At the gas price observed on 2026-11-25 (1.125 gwei), the testnet-measured
   deployment gas implies roughly 0.00104 QIE for deployment and roughly
   0.00037 QIE for one create/evidence/resolve lifecycle, before a safety
   margin. Funding 0.01 QIE would leave ample room for deployment, one proof
   run, and a small 0.001 QIE escrowed payout.
2. If mainnet is approved and funded, deploy a fresh mainnet escrow contract,
   configure a fresh mainnet operator key, run one small end-to-end mainnet
   receipt, and add its contract/transaction links here.
3. Commit and publish the final source to the public GitHub repository.
4. Final submission text must include the live demo URL, contract address,
   transaction links, track selection, limitations and prior-work disclosure.
5. Keep 2026-11-30 for breakage repair only; the implementation target is to
   finish the package before 2026-11-29.
