# Forecasting proposal alignment and expanded results

Reviewed against the submitted SG HomeFit proposal on 19 October 2026. This is
the current scope review; `FINAL_REVIEW.md` preserves the earlier four-room stage.

## Business coverage

Three-, four- and five-room flats are supported across five regional groupings.
This provides fifteen regional flat-type series and supports comparison between
smaller flats in preferred locations and larger flats elsewhere. It does not
promise every HDB flat type or separate appreciation models for every town.

All fifteen series have 117 monthly observations, January 2017–September 2026.
Minimum monthly transactions range from ten to 48. Detailed data eligibility,
excluded categories and transaction counts are in `evidence/multitype/`.

## Proposal commitments and implementation

| Proposal commitment | Implemented evidence | Qualification |
|---|---|---|
| Quality-adjusted index by region and flat type | Fifteen origin-refitted indices with structural/location controls | Current amenity/data vintages; observed controls do not remove all composition effects |
| SARIMAX with external regressors | SORA, selected-policy-package and completion-cohort proxy ablations; full ARIMAX/SARIMAX challengers | Selected family is nonseasonal ARIMAX, not a claim that all regressors improve forecasts |
| Naive and pooled LSTM benchmarks | Twelve candidate families; one LSTM pooled across fifteen series | Fixed small architecture; no claim of exhaustive tuning |
| Walk-forward MAPE and interval coverage | Three annual earlier validation origins, later-year check; 21 quarterly exploratory origins | Periods inspected during development; no pristine final test |
| Diebold–Mariano comparison | Matched six-/twelve-month losses, quarterly-overlap HAC, finite-sample adjustment, multiplicity reporting | Short, dependent sample and model selection limit inference; non-rejection is not equivalence |
| LSTM explainability | Training-background permutation Shapley explanations, all fifteen series; additivity checks and figure | Lag contributions only; no direct MRT/SORA input or causal interpretation |
| Hedonic driver explanation | Pricing workstream documents block-held-out evaluation and SHAP in `docs/model_validation.md` | Teammate-owned analysis; not rerun or claimed as forecasting's own hedonic validation |
| Interest-rate and supply scenarios | Full-regressor challenger ±1 percentage point / ±20% proxy scenarios; separate historical-error bank | Supply is approximate; shifts are assumptions, not probabilities or causal interventions |
| Profile prices and intervals | Same-date current pricing × segment growth; 1,330 supported profiles | Excludes individual-flat valuation error; unsupported flat types rejected |
| Recommender backtest support | Dated three-type growth tables; actual solver replay with dated rent/hedonic inputs | Reconstruction uses interim pricing and availability stub; not final combined conjoint/survival/UI validation |
| Contrasting-estate check | Punggol/Hougang matched-profile checks at six and twelve months | Shared growth preserves base-price ratios; does not independently predict changing town premiums |

## Selected models and accuracy

One family was selected per flat type using mean regional MAPE across the three
earlier annual origins. In this comparison all three selected ARIMA(0,1,1) with
drift plus a selected-policy-package regressor (`ARIMA_POLICY`). Parameters are
estimated separately for each of the fifteen segments.

| Flat type | Plain ARIMA validation | Selected policy ARIMA validation | Pooled LSTM validation | Selected later-year check | Naive later-year check |
|---|---:|---:|---:|---:|---:|
| 3 ROOM | 1.47% | 1.46% | 2.53% | 3.34% | 1.06% |
| 4 ROOM | 1.43% | 1.32% | 1.97% | 3.25% | 0.83% |
| 5 ROOM | 1.25% | 1.24% | 2.31% | 2.81% | 1.16% |

The incremental policy improvement is small for three- and five-room flats. The
later year favours a flat forecast. These results support the documented earlier
selection rule, not a claim of universal superiority. Regional-index MAPE is not
individual-flat pricing accuracy and is not “100 minus MAPE percent accurate.”

The pooled LSTM uses 12 log changes, 16 hidden units, twelve direct outputs,
150 epochs and three seeds. Input/target scaling and full target windows stay
within each origin's training period. Pooling changes its training population
relative to the previous four-room benchmark, so its numbers legitimately differ.

## External regressors and data availability

Three-month compounded SORA is aligned by publication date and lagged one month.
Unknown future rates are held at the last known level for baseline evaluation.
Historical original compounded-rate availability is not fully reconstructed.

The policy variable is a cumulative count of **selected** packages announced in
December 2021, September 2022 and August 2024, activated in the first following
full month. Only packages announced by the origin are allowed into future inputs.
The count assumes a common predictive increment, although packages differ and may
include offsetting grants. It is not a complete policy history or causal effect.
Official sources are recorded in `macro_sources.json`:

- [HDB, December 2021 measures](https://www.hdb.gov.sg/business-partners/estate-agents-and-salespersons/letters-to-keos/measures-to-cool-the-property-market).
- [Joint September 2022 measures](https://www.hdb.gov.sg/hdb-pulse/news/2022/property-measures2022).
- [HDB, August 2024 measures](https://www.hdb.gov.sg/hdb-pulse/news/2024/measures-to-cool-the-hdb-resale-market-and-provide-more-support-for-first-time-home-buyers).

The supply regressor is an annual completion-year-plus-five cohort, counted using
sold units by flat type and transformed with log1p, then lagged one month. The
current block inventory's contract-town codes include newer blocks without a
resale history. The corrected mapping covers 13,174 blocks; 183 outside the
supported mapping remain unmapped. The earlier address-only proxy was rejected
because it missed newer stock; affected comparisons and scenario fits were rerun.

This is **not actual MOP completion or listing supply**. HDB's MOP depends on
possession/purchase and occupation conditions, with exceptions. Current stock,
survivorship, missing key-collection dates and annual timing remain limitations.
See [HDB's MOP explanation](https://www.hdb.gov.sg/managing-my-home/home-ownership/acquiring-private-property).
The supply-only model did not improve earlier validation for any supported type.

The full challenger has positive SORA coefficients in twelve of fifteen segments.
Consequently its named rate/supply scenarios are marked **diagnostic only**, not
validated causal mechanisms for default affordability recommendations. All
selected policy coefficients are also positive: they describe observed price
regimes around endogenous policy responses, not evidence that tightening raises
prices. These are interpretation limits, not economically validated intervention
effects. The default selected model does not forecast a new unannounced package.

## Uncertainty, diagnostics and inference

Default uncertainty samples complete twelve-month × fifteen-segment historical
error matrices and optionally mirrors the entire matrix's sign. It preserves
empirical shared shocks but assumes sign symmetry and stability. Each challenger
scenario uses its own full-regressor error bank. Each bank has 21 overlapping
origins, not 21 independent market cycles; repeated Monte Carlo draws add no
historical evidence. Report coverage and width together.

The Ljung–Box check still rejects uncorrelated residuals in most selected fits.
Specifically, thirteen of fifteen reject at the nominal 5% level.
An ARIMA(1,1,1) refinement was compared for accuracy and separately diagnosed;
adding a parameter did not win earlier validation. The model is therefore an
empirically selected prototype with unresolved residual adequacy, not a model
whose white-noise assumptions have been proved. `selected_diagnostics.csv` and
`refinement_diagnostics.csv` expose the results.

Expanded ARCH checks contain some nominal 5% signals. Interpret them alongside
mean-model misspecification, limited sample and multiple testing; do not carry
forward the earlier four-room-only statement that every expanded ARCH p-value
exceeds 5%. A GARCH model is not presented as fitted or validated.

The Diebold–Mariano-style comparison uses one loss per quarterly origin at each
endpoint. It does not count all correlated region-month rows as independent
observations. Bartlett/HAC lags are one for six-month errors and three for
twelve-month errors, with horizon measured on the quarterly grid. P-values are
exploratory, with BH adjustments reported. Selection bias and data revisions are
not cured by a p-value adjustment. References:

- [Harvey, Leybourne and Newbold (1997)](https://www.sciencedirect.com/science/article/pii/S0169207096007194).
- [Diebold, use and abuse of forecast-comparison tests](https://economics.sas.upenn.edu/sites/default/files/filevault/12-035.pdf).

For selected-versus-LSTM aggregate comparisons, two-sided raw p-values were about
0.75 at six months and 0.94 at twelve months. These do not establish a significant
advantage; the positive mean loss differences on this different quarterly-origin
sample slightly favour LSTM. This does not contradict the earlier annual-origin
validation ranking, which uses a different evaluation period and all twelve months.

## Decision-level and estate checks

Historical pricing × selected growth improved MAPE in ten of twelve combinations
of origin, flat type and endpoint. The exceptions were four- and five-room flats
at the December 2024 twelve-month horizon. These are retrospective matched-cell
transaction-median checks, not realised offers or guaranteed purchasable listings.

The Punggol/Hougang check pairs otherwise equal profile-band labels. It explicitly
asserts that shared regional flat-type growth preserves the initial price ratio.
Observed later ratios can differ. Pooled ratio errors across the repeated checks
were approximately 2.8%, 4.0% and 4.8% for three-, four- and five-room flats;
the small overlapping samples do not establish a stable estate premium.

The actual weighted-GP replay returned 165, 165 and 164 recommendations under
no-change, nominal and symmetric alternatives respectively. Among matched later
transactions, within-budget rates were 53.2%, 84.8% and 97.2%. Matching counts
were 141, 145 and 142, and successful matched picks were 75, 123 and 138.
Strategies select different profiles; these rates are not forecast accuracies,
independent probability estimates, or a guarantee of future household affordability.

## What is ready and what remains team-owned

The current forecasting deliverable includes fifteen trained segments, a callable
trusted PKL, portable JSON, profile/town contracts, scenario paths, diagnostics,
LSTM explanations and historical checks. See `MULTITYPE_HANDOVER.md`.

Daniel owns final UI integration, including replacing the old four-room adapter,
using common joint scenarios and fixing/bypassing the existing deterministic
`fcast_override` issue. Comane owns the final pricing/availability models. The
group must reconcile the final pricing, preference, survival and optimiser
versions before describing the full application as validated end to end.

The implementation aligns more closely with the proposal's region-and-flat-type
coverage. Remaining data and statistical limitations are recorded rather than
represented as solved by increasing model count or geographic coverage.
