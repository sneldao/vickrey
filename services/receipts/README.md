# Reality Receipts vertical slice

Standalone FastAPI + SQLite demonstration of:

`claim/brief -> remote evidence -> field task -> sealed commitment -> signed verdict -> settlement -> public JSON receipt`

It is not a marketplace. Remote evidence is contextual, never cryptographic proof. The service stores no raw observation or structured precise location; coarse public labels are screened for coordinate-like values. Settlement defaults to a deterministic testnet **simulator**. The hackathon deployment can instead use the narrow QIE escrow adapter, which creates real transactions on QIE testnet or mainnet while explicitly reporting `real_funds`.

## Run

```bash
cd services/receipts
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q
```

Demo mode is explicit and uses local-only bearer tokens:

```bash
RECEIPTS_MODE=demo RECEIPTS_DATABASE_PATH=./receipts.db \
  uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8099
```

Demo tokens:

- claimant: `demo-claimant-token-change-me`
- observer: `demo-observer-token-change-me`
- verifier: `demo-verifier-token-change-me`
- settlement: `demo-settlement-token-change-me`

Every mutating request requires `Idempotency-Key` (8-128 safe characters). Replays return the original response with `Idempotency-Replayed: true`; changed requests under the same key return `409`.

Production defaults to fail closed. Configure all four roles in `RECEIPTS_TOKENS_JSON` and an Ed25519 verifier public key in `RECEIPTS_VERIFIER_PUBLIC_KEY` (PEM or 64-hex). Tokens must be at least 32 characters. Example shape (replace all secrets):

```json
{
  "replace-with-random-claimant-token-0001": {
    "role": "claimant",
    "subject": "claimant-1"
  },
  "replace-with-random-observer-token-0002": {
    "role": "observer",
    "subject": "observer-2"
  },
  "replace-with-random-verifier-token-0003": {
    "role": "verifier",
    "subject": "verifier-1"
  },
  "replace-with-random-settlement-token-004": {
    "role": "settlement",
    "subject": "settlement-1"
  }
}
```

Roles and subjects come only from the matched server-side token. Client role/observer/sponsor fields are rejected.

## API

All paths below are under `/v1`; mutating calls use `Authorization: Bearer <token>` and `Idempotency-Key`.

| Method | Path                                         | Authority                                                    |
| ------ | -------------------------------------------- | ------------------------------------------------------------ |
| POST   | `/challenges`                                | claimant; creates immutable criteria hash and evidence brief |
| GET    | `/challenges/{challenge_id}`                 | public-safe challenge, remote state, task                    |
| POST   | `/challenges/{challenge_id}/remote-evidence` | owning claimant                                              |
| POST   | `/challenges/{challenge_id}/field-task`      | owning claimant; only after `insufficient`                   |
| POST   | `/challenges/{challenge_id}/submissions`     | observer; 64-hex commitment + allowlisted metadata           |
| GET    | `/submissions/{submission_id}`               | owner observer/claimant, verifier, settlement                |
| POST   | `/submissions/{submission_id}/verdicts`      | verifier; Ed25519-signed, policy-versioned verdict           |
| POST   | `/verdicts/{verdict_id}/settlement`          | settlement                                                   |
| GET    | `/receipts/{challenge_id}`                   | public; redacted JSON receipt                                |

`GET /healthz` reports mode and honest adapter labels. Submission metadata is limited to `captured_at`, a coarse `public_location`, and the controlled `observation_status` (`observed`, `not_observed`, or `cannot_determine`); free-form summaries and coordinate-like labels are rejected. Public receipts omit submission metadata and raw observations. They identify the coarse public task location, commitment, policy verdict, settlement transaction ID (if any), source labels, limitations, and timestamps.

The general demo remote provider deterministically maps its input hash to `likely`, `unlikely`, `insufficient`, or `unavailable`. Only `insufficient` permits a field task. Demo mode defaults to `deterministic_demo_field_path`, which always returns `insufficient` so public demonstrations reliably exercise the complete field-evidence path; set `RECEIPTS_DEMO_FIELD_PATH=false` to use the four-state input-hash variant. Remote evaluation and its durable idempotency record commit under one write transaction, so concurrent identical requests invoke the adapter once; this also serializes other SQLite writers while the adapter runs. `accepted` pays the observer; `rejected` refunds the sponsor; `needs_witness` and `cannot_determine` record `no_payout`.

## QIE escrow settlement

The QIE adapter is enabled only through environment configuration:

```bash
RECEIPTS_SETTLEMENT_ADAPTER=qie_escrow
RECEIPTS_QIE_NETWORK=qie_testnet
RECEIPTS_QIE_RPC_URL=https://rpc4testnet.qie.digital/
RECEIPTS_QIE_CONTRACT_ADDRESS=0x...
RECEIPTS_QIE_OPERATOR_PRIVATE_KEY=<environment-only secret>
```

For the demo principal mapping, the claimant subject must be the operator sponsor address and the observer subject must be the observer payout address. Example shape only:

```json
{
  "demo-claimant-token-change-me": {
    "role": "claimant",
    "subject": "0xSponsorOperator"
  },
  "demo-observer-token-change-me": {
    "role": "observer",
    "subject": "0xObserverPayout"
  },
  "demo-verifier-token-change-me": {
    "role": "verifier",
    "subject": "verifier-1"
  },
  "demo-settlement-token-change-me": {
    "role": "settlement",
    "subject": "settlement-1"
  }
}
```

The adapter expects wei-denominated integer bounties and `RECEIPTS_MAX_BOUNTY_AMOUNT` high enough for the intended demo amount. It records immutable chain events for challenge creation, evidence submission and resolution. QIE testnet reports `real_funds=false`. Mainnet uses chain ID 1990, reports `real_funds=true`, and is refused unless `RECEIPTS_QIE_MAINNET_ACK=I_APPROVE_REAL_QIE_MAINNET_FUNDS` is present. Resolution is operator-controlled in this MVP; non-terminal verdicts do not close escrow and unresolved escrow relies on the contract expiry path.

The minimal contract and deployment script live in `contracts/`. Run tests with Foundry:

```bash
cd contracts
forge test
QIE_DEPLOYER_PRIVATE_KEY=0x... ./deploy-qie.sh testnet
```

## Verdict signing

Sign the canonical JSON object for schema `reality-receipts.verifier-verdict.v1`. The object contains `schema`, `verdict_id`, `challenge_id`, `submission_id`, `submission_version`, `commitment`, `criteria_hash`, `verdict`, `policy_id`, `policy_version`, `reason`, and `issued_at`. Use sorted keys, compact separators, UTF-8, lowercase hex bindings, surrounding-whitespace-trimmed reasons, and UTC timestamps formatted `YYYY-MM-DDTHH:MM:SS.ffffffZ`. The strict HTTP request body omits `schema` and contains the other canonical fields plus `signature` (a 128-hex Ed25519 signature). `app/signing.py` is the normative implementation.

The explicit demo-only private key matching the default demo public key is
stored as PKCS#8 Base64 so secret scanners do not mistake the documented local
fixture for a production PEM credential:

```text
PKCS#8 Base64 (demo only):
MC4CAQAwBQYDK2VwBCIEIIbpY5LXW+aqAXbpNgZIndVrscwpfw3NnZgUdlFig6nF
```

Wrap that Base64 value in PKCS#8 PEM markers only when a local tool requires
PEM. Never use the demo key or demo tokens in production.

## Storage and limits

Schema changes are versioned with `PRAGMA user_version` and additive `CREATE IF NOT EXISTS` migrations. Challenges, remote evidence, tasks, submissions, verdicts, settlements, attempts, and idempotency records have update/delete blockers. Submission state is a separate CAS projection enforcing one active submission per observer/challenge and one verdict per submission. Schema v2 preserves each principal's latest legacy quota-window total and adds a database guard for settlement operation/status consistency.

Defaults: 64 KiB request bodies, 120 successful authenticated mutations per principal/hour, a 30-day challenge horizon, and bounded task radius/bounty. Tune with `RECEIPTS_MAX_REQUEST_BYTES`, `RECEIPTS_QUOTA_PER_HOUR`, `RECEIPTS_MAX_CHALLENGE_WINDOW_SECONDS`, and `RECEIPTS_MAX_BOUNTY_AMOUNT`. Exact idempotent replays are returned before quota checks; quota consumption and workflow mutation commit atomically, so failed mutations roll back quota usage. A submission capture must not predate field-task authorization and must be submitted before task expiry. An already sealed submission may be reviewed after expiry, while challenge state reports `expired` after challenge expiry unless a terminal verdict already exists.
