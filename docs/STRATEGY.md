# Strategy — bid truthfully, pace ruthlessly

## Core: Vickrey logic

In a second-price auction the winner pays the second-highest bid, so bidding true value is dominant — no gain from shading. Even where the track's mechanism differs, start from truthful valuation, then deviate only with evidence (opponent predictability, budget exhaustion risk).

## Herd tactics (from kaggriculture)

- **Demand-aware sizing:** refuse spend where no buyer exists — map which resource pools actually clear, fill freed budget with next-best (cows over sheep where no YARN_STORE).
- **Premium-draw analysis:** identify which rounds/pools carry outsized payoff; concentrate budget there, sit out low-value rounds (conditional deployment).
- **Sim-driven versions:** v1 naive truthful → v2 budget pacing → v3 opponent model → v4+ premium targeting. Keep every version runnable; ladder decides.
- **No hardcoded values:** pull live values (budgets, pool state, opponent histories) per round; never hardcode.

## Opponent modeling (from Amon)

- Minimax framing: assume the strongest opponent response, bid the maximin.
- Track predictability: deterministic opponents get exploited, random ones get averaged.
- Keep a null/random/rote/optimal harness to verify each version beats dumber baselines before facing the field.
