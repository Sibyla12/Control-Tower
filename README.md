# Control-Tower
Real-time payment anomaly detection and root-cause diagnosis platform.

## Simulation assumptions

The datasets in `data/` are synthetic and intended for demonstrations. Financial
configuration values are illustrative rather than merchant-reported figures.
Exchange rates are fixed simulation assumptions (MXN 0.055, COP 0.00025, BRL
0.20, and USD 1.00 against USD); they are not live market rates. Transaction
`amount_usd` values are calculated with those constant rates.

Retry recovery probabilities come from `merchant_financial_config.csv`.
Processing latency is simulated using a different distribution per provider and
does not represent actual provider performance.
