from sklearn.cluster import KMeans, AffinityPropagation
from sklearn.metrics.pairwise import pairwise_distances, paired_cosine_distances
import pandas as pd
import numpy as np
import os
import argparse
import time
import torch
import pickle
import utils.config_utils as cfg_utils


def get_parser():
    parser = argparse.ArgumentParser(description='Configurations for prototype cluster')
    parser.add_argument('--config', type=str, default=None, help='parameters config file') # 'scripts/HE2HER2/cfgs/Yale.yaml'
    parser.add_argument('--opts', help='see cfgs/defaults.yaml for all options', default=None, nargs=argparse.REMAINDER)
    args = parser.parse_args()

    assert args.config is not None, "Please provide config file for parameters."
    cfg = cfg_utils.load_cfg_from_cfg_file(args.config)
    if args.opts is not None:
        cfg = cfg_utils.merge_cfg_from_list(cfg, args.opts)

    print(f"[*(//@_@)*]@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@[*(//@_@)*] CONFIG PARAMS:\n{cfg}")
    return cfg


def cluster_prototypes(args): 
    feat_paths = os.listdir(os.path.join(args.data_root_dir, "pt_files"))
    
    # intra-slide clustering (WSI-level)
    local_cluster_centroids, local_centroids_features, slideIDXs, gridIDXs = local_clustering(feat_paths)
    
    # inter-slide clustering (whole dataset)
    global_cluster_centroids, global_centroids_features, ap = global_clustering(local_centroids_features)

    # Saving AP clustering model
    with open(args.global_ap_model, 'wb') as f:
        pickle.dump(ap, f)

    # Saving the global prototype features
    np.savez(args.global_cluster_path, feature=global_centroids_features)

    # save global cluster centroids index
    save_global_centroids_idx(global_cluster_centroids, slideIDXs, gridIDXs)


def local_clustering(feature_paths):
    local_cluster_centroids = []
    wsi_names = []
    slideIDXs = []
    cluster_gridIDXs = []
    local_centroids_features = torch.Tensor()

    for i, file in enumerate(feature_paths):
        wsi_name = file.split('.')[0]
        wsi_names.append(wsi_name)
        
        if args.feat_format == '.npy':
            feat = np.load(os.path.join(args.feat_dir, file))
        elif args.feat_format == '.pt':
            feat = torch.load(os.path.join(args.feat_dir, file))
        
        begin = time.time()
        similarity = euclidean_similarity(feat)
   
        # default using negative squared euclidean distance
        ap = AffinityPropagation(preference=args.preference, damping=args.damping, affinity='precomputed', random_state=24).fit(similarity)
        cluster_centers_indices = ap.cluster_centers_indices_
        n_clusters = len(cluster_centers_indices)
        end = time.time()
        local_cluster_centroids.append(cluster_centers_indices)
        usetime = end - begin
        print("wsi {}\t File name: {}\t Use time: {:.2f}\t Number of cluster: {}".format(i + 1, file, usetime,n_clusters))
        slideIDXs.extend([i] * n_clusters)
        cluster_gridIDXs.extend(cluster_centers_indices)
        local_centroids_feature = feat[cluster_centers_indices, :]
        local_centroids_feature = local_centroids_feature.astype(np.float32)
        local_centroids_feature = torch.from_numpy(local_centroids_feature)
        local_centroids_features = torch.cat((local_centroids_features, local_centroids_feature), dim=0)
        torch.save({
        'preference': args.preference,
        'dampling': args.damping,
        'wsi_names': wsi_names,
        'centroid': local_cluster_centroids},
        args.local_cluster)
    return local_cluster_centroids, local_centroids_features, slideIDXs, cluster_gridIDXs


def global_clustering(local_centroids_features):
    local_centroids_features = np.array(local_centroids_features)
    similarity = euclidean_similarity(local_centroids_features)
    ap = AffinityPropagation(preference=args.preference, damping=args.damping, affinity='precomputed', random_state=24).fit(similarity)
    cluster_centers_indices = ap.cluster_centers_indices_
    labels = ap.labels_
    n_clusters = len(cluster_centers_indices)
    print("Estimate number of cluster: ", n_clusters)
    global_cluster_centroids = cluster_centers_indices
    global_centroids_features = local_centroids_features[global_cluster_centroids, :]
    global_centroids_features = global_centroids_features.astype(np.float32)
    return global_cluster_centroids, global_centroids_features, ap


def save_global_centroids_idx(global_cluster_centroids, slideIDXs, gridIDXs):
    centroids_slideIDXs = []
    centroids_idx = []
    for idx in global_cluster_centroids:
        slideIDX = slideIDXs[idx]
        centroids_slideIDXs.append(slideIDX)
        centroids_idx.append(gridIDXs[idx])
    torch.save({
        'slideIDX': centroids_slideIDXs,
        'gridIDX': centroids_idx},
        args.prototypes_index)

def cosine_distance(matrix1,matrix2):
    matrix1_matrix2 = np.dot(matrix1, matrix2.transpose())
    matrix1_norm = np.sqrt(np.multiply(matrix1, matrix1).sum(axis=1))
    matrix1_norm = matrix1_norm[:, np.newaxis]
    matrix2_norm = np.sqrt(np.multiply(matrix2, matrix2).sum(axis=1))
    matrix2_norm = matrix2_norm[:, np.newaxis]
    cosine_distance = np.divide(matrix1_matrix2, np.dot(matrix1_norm, matrix2_norm.transpose()))
    return cosine_distance
    

def euclidean_similarity(x, lamb):
    dists = pairwise_distances(x, metric='euclidean')
    dists =  dists / np.max(dists)
    similarity = np.exp(-dists * lamb)
    return similarity


def make_csv_columns(ndim=512):
    feature_columns = []
    for i in range(1, ndim+1):
        feature_columns.append('feature' + str(i))
    return feature_columns

    
def get_grid_index():
    gridIDXs = {}
    lib = torch.load(args.lib, map_location='cpu')
    wsi_paths = lib['slides']
    index = lib['gridIDX']
    wsi_names = [os.path.basename(wsi_path).split('.')[0] for wsi_path in wsi_paths]
    for i, wsi_name in enumerate(wsi_names):
        gridIDXs[wsi_name] = index[i]
    return gridIDXs


######################################### befor epoch training
def local_apcluster(feat, **kwargs):
    begin = time.time()
    similarity = euclidean_similarity(feat, kwargs['lamb'])

    # default using negative squared euclidean distance
    ap = AffinityPropagation(preference=kwargs['preference'], damping=kwargs['damping'], 
                             affinity='precomputed', random_state=kwargs['seed']).fit(similarity)
    cluster_centers_indices = ap.cluster_centers_indices_
    
    usetime = time.time() - begin

    local_centroids_feature = feat[cluster_centers_indices, :].type(torch.float32)
    # local_centroids_feature = torch.from_numpy(local_centroids_feature)

    return cluster_centers_indices, local_centroids_feature, usetime


def global_set_apcluster(local_centroids_features, **kwargs):
    begin = time.time()

    similarity = euclidean_similarity(local_centroids_features, kwargs['lamb'])
    ap = AffinityPropagation(preference=kwargs['preference'], damping=kwargs['damping'], 
                             affinity='precomputed', random_state=kwargs['seed']).fit(similarity)
    global_cluster_centers_indices = ap.cluster_centers_indices_
    labels = ap.labels_
    usetime = time.time() - begin

    global_centroids_features = local_centroids_features[global_cluster_centers_indices, :].type(torch.float32)
    
    return global_cluster_centers_indices, global_centroids_features, ap, usetime



if __name__ == "__main__":
    args = get_parser()
    cluster_prototypes(args)