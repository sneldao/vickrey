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
- `docker-compose.mainnet.yml` — optional operator-controlled mainnet proof
  service. Its mutation port is localhost-only; public nginx exposes only
  health and receipt GETs under `/mainnet/`, so documented demo credentials
  cannot be used to move real funds.
- `services/receipts/scripts/run_qie_flow.py` — non-secret-writing operator
  runner for a controlled end-to-end proof. It was validated against the
  public testnet service with challenge `9dded837-fb53-482f-8795-d06fbc00052f`
  and three mined testnet transactions.

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

## Draft submission-form answers

Replace the two `TBD_MAINNET` values after the funded mainnet proof. Do not
submit the testnet contract as the mainnet contract.

**Project name:** Reality Receipts by Vickrey

**Track:** AI + Autonomous Agents

**Secondary fit:** Commerce & Real World

**Repository:** <https://github.com/sneldao/vickrey>

**Live demo:** <https://vickrey.144.202.117.160.sslip.io/receipts/>

**Mainnet contract:** `TBD_MAINNET_CONTRACT`

**Mainnet proof receipt:** `TBD_MAINNET_RECEIPT_URL`

**Testnet reference contract:** [`0xb5BAEF1117B00D1B230Bf806EBFb3FEe5F7c96Ee`](https://testnet.qie.digital/address/0xb5BAEF1117B00D1B230Bf806EBFb3FEe5F7c96Ee)

**Short description:**

Reality Receipts lets an autonomous verification agent pay for bounded physical-world
evidence without publishing the raw observation. The agent posts one public-safe
claim, checks remote context first, escrows a fixed QIE bounty, receives a sealed
evidence commitment, applies an explicit verifier policy, and resolves the escrow
on QIE. The resulting public receipt links the claim criteria hash, evidence
commitment, signed verdict, settlement transaction and explorer proof.

**Detailed description:**

Reality Receipts is a Vickrey vertical slice for agentic ground truth. AI agents
can search the web, but many economically important facts are physical and time-bound:
whether a notice is posted, whether a machine is operating, whether a public object
is present, or whether a local condition changed. When remote evidence cannot resolve
such a claim, the system creates a bounded field task and pays a human observer only
after a policy-bound verdict.

The hackathon implementation is intentionally narrow and honest. It is not a generic
marketplace and does not pretend that a photo hash proves reality. The implemented
loop is: claim and criteria → remote-context check → sealed field-evidence commitment
→ Ed25519-signed verifier verdict → QIE escrow resolution → public redacted receipt.
The service never receives the raw observation or precise location. The chain stores
commitments and settlement state, not private evidence.

The new hackathon work is the QIE-native challenge workflow and settlement layer:
a Solidity escrow contract, web3 backend adapter, immutable chain-event receipt model,
operator-controlled proof runner, network-aware browser receipt UI, and public deployment.
The earlier Vickrey sealed-record primitive is disclosed as prior work; this submission
does not present that pre-existing primitive as new hackathon output.

The public interactive demo runs on QIE testnet so anyone can execute the full workflow
without spending real funds. The mainnet proof service is intentionally operator-controlled:
real-funds mutation routes are not publicly exposed with demo credentials. Judges can
inspect the mainnet contract, the read-only public mainnet receipt, and the explorer
transactions, while the interactive testnet demo demonstrates the complete product flow.

**Demo script for judges:**

1. Open the live demo and confirm the warning explains testnet/demo boundaries.
2. Run the demo workflow with the prefilled public-notice claim.
3. Watch the stages: demo boundary, challenge, remote evidence, field evidence,
   verdict, settlement, public receipt.
4. Open the three explorer links in the receipt: escrow creation, evidence commitment,
   and resolution/payout.
5. Copy the shareable receipt URL and confirm it renders without a bearer token.
6. Inspect the mainnet contract and mainnet receipt links in this submission.
7. Compare the receipt limitations with the implementation; the system labels
   synthetic context, commitment-only evidence, operator-controlled resolution,
   and testnet/mainnet funds status explicitly.

**Why QIE:**

QIE is the settlement and commerce layer: the agent creates a native-QIE escrow,
the observer evidence commitment is relayed on-chain, and the verdict resolution
pays or refunds real value. QIE is not used as a passive hash notary; it controls
the bounty state machine and payout. The design leaves room for later QIE Wallet,
QIE ID and reputation integration, but those are not falsely claimed in this MVP.

**Traction plan:**

The first traction wedge is low-value public observation challenges that produce
shareable receipts: creator dares, local service checks, public infrastructure checks,
and citizen-science observations. The next 90-day milestones are recurring sponsors,
repeat observers, completed receipt count, mainnet transaction volume, and external
agent/API callers. The current implementation is the settlement proof and product
surface needed before inviting those users.

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
2. Mainnet deployment has been explicitly approved once funded. When funding
   is confirmed, deploy a fresh mainnet escrow contract, configure the strong-token
   operator proof service, run one small end-to-end mainnet receipt with
   `scripts/run_qie_flow.py --approve-mainnet`, and add its contract/transaction
   links here.
3. Commit and publish the final source to the public GitHub repository. The
   initial implementation is published; republish the remaining mainnet-proof
   infrastructure and evidence before submission.
4. Final submission text must include the live demo URL, contract address,
   transaction links, track selection, limitations and prior-work disclosure.
5. Keep 2026-11-30 for breakage repair only; the implementation target is to
   finish the package before 2026-11-29.
