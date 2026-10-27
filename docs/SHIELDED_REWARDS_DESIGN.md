# Shielded TAZ rewards (design write-up, no payouts)

Status: design only. No payout code, no keys, no transactions. This follows the
policy in `docs/PRIVACY.md` (Keypair policy, Timing).

## Goal

Pay observers in shielded TAZ for anchored observations, without linking a
reward to a specific observation or observer on chain.

## Constraints from existing policy

- **Accounts are per role and never reused.** Anchor, verifier and reward
  accounts are distinct keypairs. Cross-account transfers are not done, because
  moving value between pools is what would spend their privacy.
- **No funding mid-window.** A funding transaction inside an observation window
  is a timing marker. The reward account is funded before the window opens, the
  same as the anchor account.
- **The chain must not link anchors.** Anchors carry no signature and no public
  key. A reward cannot be paid to a key that appears on chain next to an anchor.

## Proposed shape

1. **Reward account, separate.** One dedicated shielded account, funded
   once before the window. It only pays rewards; it never receives observation
   data.
2. **Reward is a function of the anchor, not the observer.** The verifier decides
   a reward is owed for a receipt id, then the operator pays it. Nothing in the
   reward transaction names the observation or the device.
3. **Recipient address is per reward.** Each payout goes to a fresh shielded
   address the observer supplies, so two rewards to the same observer cannot be
   linked by address.
4. **Amounts are fixed.** A constant reward per anchor, so amount does not leak
   which observation was valuable.

## Open problems

- **Who pays, and from what.** A reward needs funding, which is a real TAZ budget
  decision. Not decided here.
- **Linking via timing.** A payout shortly after an anchor could link them by
  timestamp. A delay or batching policy is needed; the value is not chosen here.
- **Sybil and fraud.** Anyone can post anchors. A reward needs a rule that stops
  one observer from farming them. Not designed here.
- **Observer identity for paying.** Paying needs the observer to hold an address,
  and that address must not be tied to the device key in the sealed record.

## Recommendation

Do not build payouts until the funding source, the delay policy and the
anti-farming rule are each decided. Those three are the real design; the
transaction mechanics are the easy part.

## Decisions needed

1. Who funds the reward account, and with what budget.
2. The payout delay or batching rule.
3. The rule that makes a reward owed.
