"""Local surface deformation, usable without bpy for numerical testing."""
import heapq
import numpy as np


def surface_weights(vertices, edges, seeds, hit, radius):
    vertices = np.asarray(vertices, dtype=float)
    adjacency = [[] for _ in vertices]
    for a, b in edges:
        w = float(np.linalg.norm(vertices[a] - vertices[b]))
        adjacency[a].append((b, w))
        adjacency[b].append((a, w))
    distance = np.full(len(vertices), np.inf)
    queue = []
    for index in seeds:
        d = float(np.linalg.norm(vertices[index] - hit))
        if d < radius:
            distance[index] = d
            heapq.heappush(queue, (d, index))
    while queue:
        d, u = heapq.heappop(queue)
        if d > distance[u]:
            continue
        for v, length in adjacency[u]:
            nd = d + length
            if nd < radius and nd < distance[v]:
                distance[v] = nd
                heapq.heappush(queue, (nd, v))
    x = np.clip(distance / radius, 0, 1)
    return 1 - (3 * x * x - 2 * x * x * x)


def deform(baseline, weights, delta, max_displacement=0.5):
    delta = np.asarray(delta, dtype=float)
    length = np.linalg.norm(delta)
    if length > max_displacement:
        delta = delta * max_displacement / length
    return np.asarray(baseline) + np.asarray(weights)[:, None] * delta
