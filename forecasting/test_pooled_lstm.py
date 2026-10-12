import unittest
import numpy as np
import pandas as pd
import torch
from .compare_pooled_lstm import SOURCE, training_arrays, fit_predict, PooledLSTM


class LSTMTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = pd.read_csv(SOURCE)
        cls.data = data[data.origin.eq(data.origin.min())].copy()

    def test_future_values_cannot_change_training_or_scaling_inputs(self):
        changed = self.data.copy()
        changed.loc[changed.kind.ne('training'), 'index'] *= 100
        a, b = training_arrays(self.data), training_arrays(changed)
        np.testing.assert_array_equal(a[0], b[0])
        np.testing.assert_array_equal(a[1], b[1])
        for region in a[2]:
            np.testing.assert_array_equal(a[2][region], b[2][region])
        # 69 levels: anchors 12..56 give 45 windows per region.
        self.assertEqual(a[0].shape, (225,12))
        self.assertEqual(a[1].shape, (225,12))

    def test_seed_reproducibility_and_checkpoint_roundtrip(self):
        a = fit_predict(self.data, 11, epochs=2)
        b = fit_predict(self.data, 11, epochs=2)
        np.testing.assert_array_equal(a[1], b[1])
        self.assertEqual(a[1].shape, (5,12))
        self.assertTrue(np.isfinite(np.exp(a[1])).all())
        loaded = PooledLSTM()
        loaded.load_state_dict(a[3].state_dict())
        x = torch.zeros(5,12,1)
        with torch.no_grad():
            torch.testing.assert_close(loaded(x), a[3](x))


if __name__ == '__main__':
    unittest.main()
