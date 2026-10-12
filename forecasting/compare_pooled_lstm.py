"""Small, fixed-spec pooled LSTM benchmark; no UI model is replaced.

Uses the origin-specific hedonic indices from compare_regional_location.
All windows and scaling are fitted using training observations only.
"""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
import torch
from torch import nn

BASE = Path(__file__).resolve().parent
SOURCE = BASE / 'outputs/regional_location/origin_specific_indices.csv'
OUT = BASE / 'outputs/pooled_lstm'
LOOKBACK, HORIZON, HIDDEN, EPOCHS = 12, 12, 16, 150
SEEDS = [11, 29, 47]


def training_arrays(frame):
    """12 past log changes -> 12 future cumulative log changes.

    Each training example's complete target must lie on/before its origin.
    Future evaluation rows are never inspected by this function.
    """
    xs, ys, latest, anchors = [], [], {}, {}
    training = frame[frame.kind.eq('training')]
    if training.origin.nunique() != 1:
        raise ValueError('Supply exactly one forecast origin')
    origin = pd.Timestamp(training.origin.iloc[0])
    for region, group in training.groupby('region'):
        group = group.sort_values('month')
        dates = pd.DatetimeIndex(pd.to_datetime(group.month))
        if dates[-1] != origin or not dates.equals(pd.date_range(dates[0], origin, freq='MS')):
            raise ValueError('Training dates must be contiguous and end at origin')
        values = group['index'].to_numpy(float)
        if not np.isfinite(values).all() or (values <= 0).any():
            raise ValueError('Indices must be finite and positive')
        logs = np.log(values)
        changes = np.diff(logs)
        for t in range(LOOKBACK, len(logs)-HORIZON):
            xs.append(changes[t-LOOKBACK:t])
            ys.append(logs[t+1:t+HORIZON+1]-logs[t])
        latest[region] = changes[-LOOKBACK:]
        anchors[region] = float(values[-1])
    if not xs:
        raise ValueError('Insufficient history')
    return np.asarray(xs), np.asarray(ys), latest, anchors


class PooledLSTM(nn.Module):
    def __init__(self):
        super().__init__()
        self.lstm = nn.LSTM(input_size=1, hidden_size=HIDDEN, batch_first=True)
        self.head = nn.Linear(HIDDEN, HORIZON)

    def forward(self, x):
        sequence, _ = self.lstm(x)
        return self.head(sequence[:, -1, :])


def fit_predict(frame, seed, epochs=EPOCHS):
    torch.manual_seed(seed)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    x, y, latest, anchors = training_arrays(frame)
    xm, xs = float(x.mean()), max(float(x.std()), 1e-8)
    ym, ys = y.mean(axis=0), np.maximum(y.std(axis=0), 1e-8)
    xt = torch.tensor((x-xm)/xs, dtype=torch.float32).unsqueeze(-1)
    yt = torch.tensor((y-ym)/ys, dtype=torch.float32)
    model = PooledLSTM()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.005, weight_decay=0.001)
    model.train()
    for _ in range(epochs):
        optimizer.zero_grad()
        loss = nn.functional.mse_loss(model(xt), yt)
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
    regions = sorted(latest)
    inputs = torch.tensor((np.asarray([latest[r] for r in regions])-xm)/xs,
                          dtype=torch.float32).unsqueeze(-1)
    model.eval()
    with torch.no_grad():
        growth = model(inputs).numpy()*ys+ym
    metadata = dict(seed=seed, epochs=epochs, training_windows=len(x), input_mean=xm,
                    input_std=xs, target_mean=ym.tolist(), target_std=ys.tolist(),
                    final_training_loss=float(loss.detach()))
    return regions, growth, anchors, model, metadata


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    frame = pd.read_csv(SOURCE)
    predictions, seed_rows, audit = [], [], []
    origins = sorted(frame.origin.unique())
    for origin in origins:
        subset = frame[frame.origin.eq(origin)]
        draws = []
        for seed in SEEDS:
            regions, growth, anchors, model, metadata = fit_predict(subset, seed)
            draws.append(growth)
            checkpoint = OUT / f'lstm_{origin}_{seed}.pt'
            torch.save(dict(state_dict=model.state_dict(), metadata=metadata,
                            lookback=LOOKBACK, horizon=HORIZON, hidden=HIDDEN), checkpoint)
            audit.append(dict(origin=origin, **metadata))
            print(f'{origin} seed {seed}: {metadata["training_windows"]} windows', flush=True)
        mean_growth = np.mean(draws, axis=0)
        stage = 'later_period_check' if origin == origins[-1] else 'validation'
        for i, region in enumerate(regions):
            actual = subset[subset.region.eq(region) & subset.kind.eq('evaluation_frozen_coefficients')].sort_values('month')
            dates = pd.date_range(pd.Timestamp(origin)+pd.offsets.MonthBegin(), periods=HORIZON, freq='MS')
            if not pd.DatetimeIndex(pd.to_datetime(actual.month)).equals(dates):
                raise ValueError('Evaluation dates do not match forecast horizon')
            for h, (_, row) in enumerate(actual.iterrows()):
                common = dict(region=region, flat_type='4 ROOM', stage=stage,
                              origin=origin, month=row.month, horizon=h+1, actual_index=float(row['index']))
                predictions.append(dict(**common, model='pooled_LSTM',
                                        forecast_index=anchors[region]*float(np.exp(mean_growth[i,h]))))
                for j, seed in enumerate(SEEDS):
                    seed_rows.append(dict(**common, seed=seed,
                                          forecast_index=anchors[region]*float(np.exp(draws[j][i,h]))))
    pred = pd.DataFrame(predictions)
    pred.to_csv(OUT / 'predictions.csv', index=False)
    pd.DataFrame(seed_rows).to_csv(OUT / 'seed_predictions.csv', index=False)
    baselines = pd.read_csv(BASE / 'outputs/regional_location/predictions.csv')
    combined = pd.concat([baselines, pred], ignore_index=True)
    combined['APE_pct'] = 100*(combined.forecast_index/combined.actual_index-1).abs()
    metrics = combined.groupby(['stage','model','region']).agg(MAPE_pct=('APE_pct','mean'), n=('APE_pct','size')).reset_index()
    metrics.to_csv(OUT / 'metrics_by_region.csv', index=False)
    summary = metrics.groupby(['stage','model']).agg(mean_region_MAPE_pct=('MAPE_pct','mean'),regions=('region','nunique')).reset_index()
    summary.to_csv(OUT / 'comparison.csv', index=False)
    manifest = dict(torch_version=torch.__version__, source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                    lookback=LOOKBACK, horizon=HORIZON, hidden_units=HIDDEN, epochs=EPOCHS, seeds=SEEDS,
                    learning_rate=0.005, weight_decay=0.001, seed_ensemble='mean log growth; geometric mean index',
                    audit=audit, limitations=[
                        'Fixed architecture and epochs; no tuning or cherry-picking seeds after seeing errors.',
                        'Overlapping windows are not independent samples; five short regional histories only.',
                        'Static amenity and current data vintage limitations inherited from hedonic experiment.',
                        'Later period has previously been inspected; not an untouched holdout.',
                        'Point forecasts only. Seed spread is not a prediction interval.',
                        'No SORA, SHAP, announcement-date features or deployment in this benchmark.'])
    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(summary.to_string(index=False))


if __name__ == '__main__':
    main()
