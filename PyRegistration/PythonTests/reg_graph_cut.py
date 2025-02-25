
import networkx as nx
import numpy as np
from skimage.future.graph import _ncut
from skimage.future.graph import _ncut_cy
from scipy.sparse import linalg
import random


def cut_threshold(labels, rag, thresh, in_place=True):
    """Combine regions separated by weight less than threshold.

    Given an image's labels and its RAG, output new labels by
    combining regions whose nodes are separated by a weight less
    than the given threshold.

    Parameters
    ----------
    labels : ndarray
        The array of labels.
    rag : RAG
        The region adjacency graph.
    thresh : float
        The threshold. Regions connected by edges with smaller weights are
        combined.
    in_place : bool
        If set, modifies `rag` in place. The function will remove the edges
        with weights less that `thresh`. If set to `False` the function
        makes a copy of `rag` before proceeding.

    Returns
    -------
    out : ndarray
        The new labelled array.


    References
    ----------
    .. [1] Alain Tremeau and Philippe Colantoni
           "Regions Adjacency Graph Applied To Color Image Segmentation"
           http://citeseerx.ist.psu.edu/viewdoc/summary?doi=10.1.1.11.5274

    """
    if not in_place:
        rag = rag.copy()

    # Because deleting edges while iterating through them produces an error.
    to_remove = [(x, y) for x, y, d in rag.edges_iter(data=True)
                 if d['weight'] >= thresh]
    rag.remove_edges_from(to_remove)

    comps = nx.connected_components(rag)

    # We construct an array which can map old labels to the new ones.
    # All the labels within a connected component are assigned to a single
    # label in the output.
    map_array = np.arange(labels.max() + 1, dtype=labels.dtype)
    for i, nodes in enumerate(comps):
        for node in nodes:
            for label in rag.node[node]['labels']:
                map_array[label] = i

    return map_array[labels]


def cut_normalized(labels, rag, thresh=0.001, num_cuts=10, in_place=True,
                   max_edge=1.0):
    """Perform Normalized Graph cut on the Region Adjacency Graph.

    Given an image's labels and its similarity RAG, recursively perform
    a 2-way normalized cut on it. All nodes belonging to a subgraph
    that cannot be cut further are assigned a unique label in the
    output.

    Parameters
    ----------
    labels : ndarray
        The array of labels.
    rag : RAG
        The region adjacency graph.
    thresh : float
        The threshold. A subgraph won't be further subdivided if the
        value of the N-cut exceeds `thresh`.
    num_cuts : int
        The number or N-cuts to perform before determining the optimal one.
    in_place : bool
        If set, modifies `rag` in place. For each node `n` the function will
        set a new attribute ``rag.node[n]['ncut label']``.
    max_edge : float, optional
        The maximum possible value of an edge in the RAG. This corresponds to
        an edge between identical regions. This is used to put self
        edges in the RAG.

    Returns
    -------
    out : ndarray
        The new labeled array.

    Examples
    --------


    References
    ----------
    .. [1] Shi, J.; Malik, J., "Normalized cuts and image segmentation",
           Pattern Analysis and Machine Intelligence,
           IEEE Transactions on, vol. 22, no. 8, pp. 888-905, August 2000.

    """
    if not in_place:
        rag = rag.copy()

    for node in rag.nodes_iter():
        rag.add_edge(node, node, weight=max_edge)

    _ncut_relabel(rag, thresh, num_cuts)

    map_array = np.zeros(labels.max() + 1, dtype=labels.dtype)
    # Mapping from old labels to new
    for n, d in rag.nodes_iter(data=True):
        map_array[d['labels']] = d['ncut label']

    return map_array[labels]


def partition_by_cut(cut, rag):
    """Compute resulting subgraphs from given bi-parition.

    Parameters
    ----------
    cut : array
        A array of booleans. Elements set to `True` belong to one
        set.
    rag : RAG
        The Region Adjacency Graph.

    Returns
    -------
    sub1, sub2 : RAG
        The two resulting subgraphs from the bi-partition.
    """
    # `cut` is derived from `D` and `W` matrices, which also follow the
    # ordering returned by `rag.nodes()` because we use
    # nx.to_scipy_sparse_matrix.

    # Example
    # rag.nodes() = [3, 7, 9, 13]
    # cut = [True, False, True, False]
    # nodes1 = [3, 9]
    # nodes2 = [7, 10]

    nodes1 = [n for i, n in enumerate(rag.nodes()) if cut[i]]
    nodes2 = [n for i, n in enumerate(rag.nodes()) if not cut[i]]

    sub1 = rag.subgraph(nodes1)
    sub2 = rag.subgraph(nodes2)

    return sub1, sub2


def get_min_ncut(ev, d, w, num_cuts):
    """Threshold an eigenvector evenly, to determine minimum ncut.

    Parameters
    ----------
    ev : array
        The eigenvector to threshold.
    d : ndarray
        The diagonal matrix of the graph.
    w : ndarray
        The weight matrix of the graph.
    num_cuts : int
        The number of evenly spaced thresholds to check for.

    Returns
    -------
    mask : array
        The array of booleans which denotes the bi-partition.
    mcut : float
        The value of the minimum ncut.
    """
    mcut = np.inf
    mn = ev.min()
    mx = ev.max()

    # If all values in `ev` are equal, it implies that the graph can't be
    # further sub-divided. In this case the bi-partition is the the graph
    # itself and an empty set.
    min_mask = np.zeros_like(ev, dtype=np.bool)
    if np.allclose(mn, mx):
        return min_mask, mcut

    # Refer Shi & Malik 2001, Section 3.1.3, Page 892
    # Perform evenly spaced n-cuts and determine the optimal one.
    for t in np.linspace(mn, mx, num_cuts, endpoint=False):
        mask = ev > t
        cost = _ncut.ncut_cost(mask, d, w)
        if cost < mcut:
            min_mask = mask
            mcut = cost

    return min_mask, mcut


# def _label_all(rag, attr_name):
#     """Assign a unique integer to the given attribute in the RAG.
#
#     This function assumes that all labels in `rag` are unique. It
#     picks up a random label from them and assigns it to the `attr_name`
#     attribute of all the nodes.
#
#     rag : RAG
#         The Region Adjacency Graph.
#     attr_name : string
#         The attribute to which a unique integer is assigned.
#     """
#     node = min(rag.nodes())
#     new_label = rag.node[node]['labels'][0]
#     for n, d in rag.nodes_iter(data=True):
#         d[attr_name] = new_label

def _label_all(rag,label):
    for nd in rag.nodes():
        rag.node[nd]['label'] = label


def _ncut_relabel(rag, thresh, num_cuts):
    """Perform Normalized Graph cut on the Region Adjacency Graph.

    Recursively partition the graph into 2, until further subdivision
    yields a cut greater than `thresh` or such a cut cannot be computed.
    For such a subgraph, indices to labels of all its nodes map to a single
    unique value.

    Parameters
    ----------
    labels : ndarray
        The array of labels.
    rag : RAG
        The region adjacency graph.
    thresh : float
        The threshold. A subgraph won't be further subdivided if the
        value of the N-cut exceeds `thresh`.
    num_cuts : int
        The number or N-cuts to perform before determining the optimal one.
    map_array : array
        The array which maps old labels to new ones. This is modified inside
        the function.
    """
    d, w = _ncut.DW_matrices(rag)
    m = w.shape[0]
    curr_label = random.randint(1,100)

    if m > 2:
        d2 = d.copy()
        # Since d is diagonal, we can directly operate on its data
        # the inverse of the square root
        d2.data = np.reciprocal(np.sqrt(d2.data, out=d2.data), out=d2.data)

        # Refer Shi & Malik 2001, Equation 7, Page 891
        vals, vectors = linalg.eigsh(d2 * (d - w) * d2, which='SM',
                                     k=min(100, m - 2))

        # Pick second smallest eigenvector.
        # Refer Shi & Malik 2001, Section 3.2.3, Page 893
        vals, vectors = np.real(vals), np.real(vectors)
        index2 = _ncut_cy.argmin2(vals)
        ev = vectors[:, index2]

        cut_mask, mcut = get_min_ncut(ev, d, w, num_cuts)
        if (mcut < thresh):
            # Sub divide and perform N-cut again
            # Refer Shi & Malik 2001, Section 3.2.5, Page 893
            sub1, sub2 = partition_by_cut(cut_mask, rag)

            _ncut_relabel(sub1, thresh, num_cuts)
            _ncut_relabel(sub2, thresh, num_cuts)
            return

    # The N-cut wasn't small enough, or could not be computed.
    # The remaining graph is a region.
    # Assign `ncut label` by picking any label from the existing nodes, since
    # `labels` are unique, `new_label` is also unique.
    _label_all(rag, curr_label)
