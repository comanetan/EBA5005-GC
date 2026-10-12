# SG HomeFit Optimiser — User Guide

**Tool:** [SG HomeFit Optimiser](https://claude.ai/artifact/KjCLZbJXDZ7H2StsooGupf) (interactive calculator)
**Audience:** teammates, graders, or anyone reviewing the Optimisation Lead workstream who wants to interact with the actual decision logic rather than read about it.

The tool has three tabs. Each is a live calculator — change any number and every table re-solves immediately. Nothing is submitted anywhere; all the math runs in your browser.

---

## Tab 1 — Viewing-Time Allocation

**Question it answers:** a household has shortlisted two flats and a limited number of hours this month for viewings, follow-ups and offers. How should those hours be split to capture the most expected value, given that each flat's market can only usefully absorb so much attention before matching listings run out?

**Inputs:**
| Field | Meaning |
|---|---|
| $ value captured per hour (A / B) | How much expected benefit one hour of pursuing that profile is worth |
| $ cost of an hour (A / B) | The opportunity cost of your own time (commute, work taken off, etc.) |
| Liquidity cap (A / B) | The most hours worth spending on that profile before the market itself runs out of matching listings — a thin market (few recent sales) caps this low |
| Hours needed per unit (A / B) | Commute-adjusted effort — a farther profile costs more hours per unit of progress |
| Total house-hunting hours this month | Your overall time budget |
| Agent slots needed per hour (A / B) + slots available | A second limited resource (your agent's calendar) |

**Reading the output:**
- **Corner points** table — every feasible combination of hours that lies at a "corner" of what's allowed; the one in green is best. This is the same corner-point method used to solve any two-variable linear program by hand.
- **Shadow price** — if a resource row is *binding* (fully used up), its shadow price says how much more expected value one extra unit of that resource would buy. A *slack* resource (not fully used) always has a shadow price of $0 — there's spare capacity, so one more unit of it buys nothing.
- **Reduced cost** — if a profile gets **zero** hours in the optimal split, its reduced cost says how much its hourly value would need to rise before it became worth any effort at all.

---

## Tab 2 — Stretch-Budget Allocation

**Question it answers:** beyond the cheapest flat that already meets the hard requirements, a household often has some extra budget to spend improving on *either* MRT proximity *or* lease length — never both for free, since each costs a different market rate per unit. Given a priority (which goal matters more) and a stretch budget, how should it be split?

**Inputs:**
| Field | Meaning |
|---|---|
| Market rate: $ per km closer to MRT | How much the market actually charges for proximity (from the project's own hedonic pricing model) |
| Market rate: $ per extra year of lease | Same, for lease length |
| Stretch budget | How much extra the household is willing to pay above the cheapest baseline flat |
| Target: km closer to MRT wanted / extra lease-years wanted | What "good enough" looks like for each goal |
| Top priority | Which goal gets funded first if the stretch budget can't cover both |

**Reading the output:**
- **Step 1** fully funds the top-priority goal, up to what the budget allows.
- **Step 2** spends whatever's left on the second goal.
- A goal that still falls short after its step shows a positive **shortfall** (this is the deviation the method is built to minimise). Switch "Top priority" to see the shortfall move from one goal to the other — that's the priority mechanism working as intended, not a bug.

---

## Tab 3 — Final Recommender

**Question it answers:** given a full set of candidate HDB profiles (town, price, MRT distance, remaining lease) and a household's budget, lease floor, MRT target and preference weight, which exact set of `k` profiles should be shortlisted?

**Inputs:**
- Household fields (budget, minimum lease, target MRT distance, number of picks `k`, MRT preference weight).
- The candidate-profile table itself is editable — change any town's price, distance or lease, or overwrite the sample rows entirely with your own figures.

**Reading the output:**
- Press **Solve the 0-1 program** to brute-force every feasible combination of `k` profiles (a profile only qualifies if it's within budget and meets the lease floor; at most one profile per town is picked).
- The **combinations table** ranks every feasible shortlist by its net objective (total surplus minus total deviation); the best is highlighted.
- The **chosen shortlist** panel shows the winning picks individually.
- This tab is a small, brute-force stand-in for the real pipeline's solver (`recommender_v2.py`), which runs the identical logic as a proper integer program over the full set of HDB profiles rather than eight sample rows.

---

## Tips

- All three tabs are independent — changing Tab 1's inputs has no effect on Tab 2 or 3.
- The candidate table in Tab 3 keeps whatever you type until you reload the page; there's no save/export, so copy out any numbers you want to keep.
- If a tab's result area shows "No feasible region" or "No feasible k-combination," a constraint is too tight (e.g. the budget is below every candidate's price, or the stretch budget is $0) — loosen it and the tables repopulate.

For where each method traces back to the course syllabus, and how it's validated, see **OPTIMISER_METHODOLOGY_REPORT.md** in this folder — that detail is deliberately kept out of the tool itself so the interface stays about the decision, not the citation.
