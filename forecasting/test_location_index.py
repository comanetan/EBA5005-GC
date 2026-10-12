import unittest
import numpy as np
import pandas as pd
from .compare_regional_location import load_features, CONTROLS, OUT
from .compare_sarimax_rates import refit_index

class LocationIndexTests(unittest.TestCase):
    def test_future_prices_and_locations_do_not_change_training_index(self):
        OUT.mkdir(parents=True,exist_ok=True)
        df=load_features()
        df=df[df.region.eq("NORTH-EAST")].copy()
        origin,end=pd.Timestamp("2024-09-01"),pd.Timestamp("2025-09-01")
        original,_=refit_index(df,origin,end,extra_controls=CONTROLS)
        future=df.month>origin
        df.loc[future,"resale_price"]*=1.5
        df.loc[future,"log_dist_mrt"]+=0.5
        altered,_=refit_index(df,origin,end,extra_controls=CONTROLS)
        np.testing.assert_allclose(original,altered)

if __name__=="__main__":unittest.main()
