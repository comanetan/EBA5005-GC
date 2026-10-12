"""SG HomeFit models. Every public function takes `as_of` ("YYYY-MM"): it only uses data up to and including that month,
so the backtest can re-run the whole chain at past dates.

    from homefit import profiles, hedonic, survival
    rows = profiles.profile_rows("2023-06")          # block x flat type x storey band, banded as of Jun 2023
    model = hedonic.fit("2023-06");  prices = hedonic.price_profiles(model, "2023-06")
    cox = survival.fit("2023-06");   waits = survival.profile_waits(cox, "2023-06")
"""
