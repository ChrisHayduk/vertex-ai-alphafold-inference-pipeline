from kfp.v2 import dsl
from kfp.v2.dsl import Artifact, Input, Output
import config as config

@dsl.component(
    base_image=config.ALPHAFOLD_COMPONENTS_IMAGE,
    packages_to_install=['google-cloud-storage']
)
def aggregate_features_across_chains(
    per_chain_features_dir: str,  # JSON string from create_run_id
    sequences: Input[Artifact],
    is_homomer_or_monomer: str,
    output_features_path: str,    # GCS path
    features: Output[Artifact],
):
    """Aggregates features across chains for multimer prediction."""
    import pickle
    import tempfile
    import json
    from google.cloud import storage
    import logging
    from alphafold.data import feature_processing, pipeline_multimer
    import os
    import numpy as np

    storage_client = storage.Client()
    
    # Load all chain features from GCS
    all_chain_features = {}
    chain_info = sequences.metadata['chain_info']
    
    # Parse the features paths from JSON
    paths_info = json.loads(per_chain_features_dir)
    
    # Helper function to print shapes of key features
    def print_feature_shapes(chain_id, features_dict, prefix=""):
        # This function prints the shapes of some critical arrays
        keys_to_check = [
            'msa', 'msa_all_seq', 'template_aatype', 'aatype', 
            'num_alignments', 'num_alignments_all_seq'
        ]
        print(f"{prefix}Feature shapes for chain {chain_id}:")
        for key in keys_to_check:
            if key in features_dict:
                val = features_dict[key]
                if isinstance(val, np.ndarray):
                    print(f"  {key}: shape {val.shape}")
                else:
                    print(f"  {key}: not an array (type: {type(val)})")
            else:
                print(f"  {key}: not found in features")
        print("-------------------------------------------------")

    for chain_data in chain_info:
        chain_id = chain_data['chain_id']
        
        # Get the features path for this chain
        if chain_id not in paths_info['chains']:
            raise ValueError(f"No path information found for chain {chain_id}")
            
        features_path = paths_info['chains'][chain_id]
        
        # Parse bucket and blob path
        bucket_name = features_path.replace('gs://', '').split('/')[0]
        blob_path = '/'.join(features_path.replace('gs://', '').split('/')[1:]) + '/features.pkl'
        
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        
        if not blob.exists():
            raise FileNotFoundError(f"Features file not found in GCS for chain {chain_id}: gs://{bucket_name}/{blob_path}")
        
        # Download and process features
        with tempfile.NamedTemporaryFile() as temp_file:
            blob.download_to_filename(temp_file.name)
            with open(temp_file.name, 'rb') as f:
                chain_features = pickle.load(f)
                print(f"Chain features keys before monomer processing: {chain_features.keys()}")
                
                # Print shapes before monomer processing
                print_feature_shapes(chain_id, chain_features, prefix="Before monomer processing:")
                
                # Convert monomer features to multimer format
                chain_features = pipeline_multimer.convert_monomer_features(
                    monomer_features=chain_features,
                    chain_id=chain_id
                )
                print(f"Chain features keys after monomer processing: {chain_features.keys()}")
                
                # Print shapes after monomer processing
                print_feature_shapes(chain_id, chain_features, prefix="After monomer processing:")

                all_chain_features[chain_id] = chain_features
    
    # Add assembly features
    all_chain_features = pipeline_multimer.add_assembly_features(all_chain_features)

    # Print shapes after adding assembly features
    for cid, feats in all_chain_features.items():
        print_feature_shapes(cid, feats, prefix="After assembly features:")

    if is_homomer_or_monomer == 'true' and len(all_chain_features) == 1:
        # For monomers, just use the single chain features
        chain_id = next(iter(all_chain_features))
        np_example = all_chain_features[chain_id]
    else:
        # For multimers, pair and merge the features
        print(f"Pairing and merging {len(all_chain_features)} chains")
        print(f"All chain features keys: {all_chain_features.keys()}")

        # Print shapes before pair_and_merge
        for cid, feats in all_chain_features.items():
            print_feature_shapes(cid, feats, prefix="Before pair_and_merge:")

        np_example = feature_processing.pair_and_merge(
            all_chain_features=all_chain_features)
        
        # Print shapes after pair_and_merge
        print_feature_shapes("merged", np_example, prefix="After pair_and_merge:")
        
        print_feature_shapes("merged", np_example, prefix="Before pad_msa:")
        np_example = pipeline_multimer.pad_msa(np_example, 512)
        print_feature_shapes("merged", np_example, prefix="After pad_msa:")
        
    # Use the full protein features path from paths_info if available
    if 'full_protein' in paths_info:
        output_features_path = paths_info['full_protein']
    
    # Save merged features to GCS
    dest_bucket_name = output_features_path.replace('gs://', '').split('/')[0]
    dest_prefix = '/'.join(output_features_path.replace('gs://', '').split('/')[1:])
    dest_blob_path = os.path.join(dest_prefix, 'all_chain_features.pkl')
    dest_bucket = storage_client.bucket(dest_bucket_name)
    dest_blob = dest_bucket.blob(dest_blob_path)
    
    try:
        with tempfile.NamedTemporaryFile() as temp_file:
            with open(temp_file.name, 'wb') as f:
                pickle.dump(np_example, f, protocol=4)
            dest_blob.upload_from_filename(temp_file.name)
    except Exception as e:
        raise RuntimeError(f"Failed to save features to GCS at {output_features_path}: {str(e)}")
    
    features.uri = os.path.join(output_features_path, 'all_chain_features.pkl')
    features.metadata = {
        'is_homomer_or_monomer': is_homomer_or_monomer,
        'num_chains': len(all_chain_features)
    }

    # Print debug information
    logging.info(f"Successfully processed {len(all_chain_features)} chains")
    logging.info(f"Output features saved to: {output_features_path}")
    logging.info(f"Features metadata: {features.metadata}")
