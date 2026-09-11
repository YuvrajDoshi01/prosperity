---
name: Round 1 Manual Challenge - Auction Solver
description: P4 Round 1 introduced a new manual challenge format (stale-order-book clearing auction) not seen in P1-P3. Solver and optimal orders documented.
type: project
originSessionId: 48a77d8f-dbe3-4a9b-a514-9a226f1041cd
---
P4 Round 1 manual challenge ("An Intarian Welcome") is a uniform-price clearing auction - new format not in any previous Prosperity edition.

**Why:** Past manual challenges were FX arb, two-price bidding, game theory crowding, or news allocation. This stale-order-book auction required a custom solver.

**How to apply:** `trader-logic/auction_solver.py` is reusable for future auction-type manual challenges. Update the order book dicts and re-run. The key exploit (bid above target clearing price with capped volume for price priority) applies whenever we see the full book and submit last.

Optimal orders for R1: Flax BUY@30 vol 9,999 (clearing 29, profit 9,999), Mushroom BUY@17 vol 19,999 (clearing 16, profit 77,996). Total 87,995 XIRECs.
