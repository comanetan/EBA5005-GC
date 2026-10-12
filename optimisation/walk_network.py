# -*- coding: utf-8 -*-
"""
Walking-network distances (replaces straight-line distance).

1. Download Singapore's pedestrian network from OpenStreetMap via osmnx
   (network_type="walk": footpaths, linkways, overhead bridges, underpasses,
   plus walkable roads; excludes expressways).
2. For each amenity layer, run ONE multi-source Dijkstra from all of that
   layer's points at once -> walking distance from every network node to the
   nearest amenity. Then snap each HDB block to its nearest node.
   Cost: one graph search per layer, not one per block.

Caveats: OSM completeness varies (some covered linkways / void-deck
shortcuts are unmapped); blocks and amenities are snapped to the nearest
network node (snap distance is reported and added on).
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
DATA = os.path.join(HERE, "data")
# UNSIMPLIFIED: nodes at every path vertex, so snapping a block/bus stop lands within metres of its
# true position. (A simplified graph keeps only junctions; mid-street points snapped to a junction
# up to ~100m away inflated short walks -- median bus-stop detour came out 2.2x, an artifact.)
GRAPH_PATH = os.path.join(DATA, "sg_walk_network_unsimplified.graphml")

ox.settings.use_cache = True
ox.settings.log_console = False
ox.settings.requests_timeout = 600


def get_graph():
    if os.path.exists(GRAPH_PATH):
        return ox.load_graphml(GRAPH_PATH)
    blocks = pd.read_csv(os.path.join(DATA, "block_accessibility.csv"))
    pad = 0.02  # ~2.2km so amenities just beyond the outermost blocks are included
    bbox = (blocks["lon"].min() - pad, blocks["lat"].min() - pad, blocks["lon"].max() + pad, blocks["lat"].max() + pad)
    t = time.time()
    G = ox.graph_from_bbox(bbox, network_type="walk", simplify=False, retain_all=False)
    print(f"Downloaded walk network: {G.number_of_nodes():,} nodes, {G.number_of_edges():,} edges in {time.time()-t:.0f}s", flush=True)
    ox.save_graphml(G, GRAPH_PATH)
    return G


def nearest_nodes_with_snap(G, lons, lats):
    nodes, snap = ox.distance.nearest_nodes(G, X=lons, Y=lats, return_dist=True)
    return np.asarray(nodes), np.asarray(snap)  # snap in metres (graph is unprojected -> great-circle)


def to_simple_graph(G_und):
    """Collapse the osmnx MultiGraph to a simple Graph keeping the SHORTEST of any parallel edges."""
    Gs = nx.Graph()
    Gs.add_nodes_from(G_und.nodes(data=True))
    for u, v, data in G_und.edges(data=True):
        L = float(data.get("length", 0.0))
        if not Gs.has_edge(u, v) or L < Gs[u][v]["length"]:
            Gs.add_edge(u, v, length=L)
    return Gs


def add_connector_edges(Gs, max_m=25.0):
    """Bridge OSM gaps: join every pair of nodes within max_m that is not already an edge.
    Stands in for unmapped zebra crossings, void-deck walk-throughs and covered linkways inside
    HDB estates (route traces showed 127m straight-line walks routed as 1.3km). Risk: may also
    cross real barriers narrower than max_m (drains, fences), so max_m is kept below typical road width."""
    from sklearn.neighbors import BallTree
    nodes = [n for n in Gs.nodes if n != "__SRC__"]
    xy = np.radians([[Gs.nodes[n]["y"], Gs.nodes[n]["x"]] for n in nodes])
    tree = BallTree(xy, metric="haversine")
    R = 6_371_000.0
    ind, dist = tree.query_radius(xy, r=max_m / R, return_distance=True)
    added = 0
    for i, (nbrs, ds) in enumerate(zip(ind, dist)):
        u = nodes[i]
        for j, d in zip(nbrs, ds):
            if j <= i:
                continue
            v = nodes[j]
            if not Gs.has_edge(u, v):
                Gs.add_edge(u, v, length=float(d * R))
                added += 1
    return added


def walk_distance_to_layer(Gs, block_nodes, block_snap, layer_lons, layer_lats, cutoff_m=5000, snap_graph=None):
    """Gs: simple undirected graph (to_simple_graph). snap_graph: graph used for nearest-node lookup."""
    src_nodes, src_snap = nearest_nodes_with_snap(snap_graph if snap_graph is not None else Gs, layer_lons, layer_lats)
    SRC = "__SRC__"
    Gs.add_node(SRC)
    for n, s in zip(src_nodes, src_snap):
        if not Gs.has_edge(SRC, n) or s < Gs[SRC][n]["length"]:
            Gs.add_edge(SRC, n, length=float(s))  # amenity's own snap offset counts toward the walk
    try:
        dist = nx.single_source_dijkstra_path_length(Gs, SRC, cutoff=cutoff_m, weight="length")
    finally:
        Gs.remove_node(SRC)
    d = np.array([dist.get(n, np.nan) for n in block_nodes], dtype=float)
    return (d + block_snap) / 1000.0  # km, including the block's own snap distance


if __name__ == "__main__":
    G = get_graph()
    print(f"Graph: {G.number_of_nodes():,} nodes, {G.number_of_edges():,} edges")
