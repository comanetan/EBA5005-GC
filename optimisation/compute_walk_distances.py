# -*- coding: utf-8 -*-
"""
Walking-network distance from every HDB block to the nearest amenity of each
layer (one multi-source Dijkstra per layer). Writes data/block_walk_distances.csv,
which block_accessibility.py merges in as walk_* columns.

School TIERS deliberately stay straight-line: MOE's P1 home-school distance
categories are straight-line, so walking distance would mis-assign tiers.
"""
import os
import sys
import time

import networkx as nx
import numpy as np
import osmnx as ox
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from walk_network import get_graph, nearest_nodes_with_snap, walk_distance_to_layer, to_simple_graph, add_connector_edges  # noqa: E402
from block_accessibility import load_amenity_layers  # noqa: E402

DATA = os.path.join(HERE, "data")

WALK_LAYERS = ["mrt_exit", "mrt_exit_base", "hawker", "supermarket", "chas_clinic", "park",
               "primary_school", "primary_elite", "childcare", "bus_stop"]


if __name__ == "__main__":
    t0 = time.time()
    G = get_graph()
    G_und = ox.convert.to_undirected(G)
    Gs = to_simple_graph(G_und)
    print(f"Graph ready: {G_und.number_of_nodes():,} nodes ({time.time()-t0:.0f}s)", flush=True)
    # --connect M : bridge OSM gaps with connector edges <= M metres (see add_connector_edges)
    connect_m = float(sys.argv[sys.argv.index("--connect") + 1]) if "--connect" in sys.argv else 0.0
    if connect_m > 0:
        n_add = add_connector_edges(Gs, connect_m)
        print(f"Added {n_add:,} connector edges <= {connect_m:.0f}m", flush=True)
    out_name = f"block_walk_distances_connect{int(connect_m)}m.csv" if connect_m > 0 else "block_walk_distances.csv"

    blocks = pd.read_csv(os.path.join(DATA, "block_accessibility.csv"))
    bnodes, bsnap = nearest_nodes_with_snap(G_und, blocks["lon"].values, blocks["lat"].values)
    out = pd.DataFrame({"query": blocks["query"], "walk_snap_m": bsnap.round(1)})
    print(f"Blocks snapped: median snap {np.median(bsnap):.0f}m, p95 {np.percentile(bsnap, 95):.0f}m", flush=True)

    layers, _ = load_amenity_layers()
    layer_names = WALK_LAYERS + [k for k in layers if k.startswith("mrt_exit_opened_")]
    for name in layer_names:
        pts = layers[name]
        t = time.time()
        out[f"walk_{name}_km"] = walk_distance_to_layer(Gs, bnodes, bsnap, pts["lon"].values, pts["lat"].values, snap_graph=G_und)
        print(f"  {name}: {len(pts)} points, median walk {np.nanmedian(out[f'walk_{name}_km'])*1000:.0f}m, "
              f"unreachable(<5km) {out[f'walk_{name}_km'].isna().mean()*100:.2f}% ({time.time()-t:.0f}s)", flush=True)

    out.to_csv(os.path.join(DATA, out_name), index=False)
    print(f"Saved {out_name} ({time.time()-t0:.0f}s total)")
