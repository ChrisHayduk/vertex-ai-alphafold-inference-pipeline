# Copyright 2021 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""A component encapsulating AlphaFold model predict."""


from kfp.v2 import dsl
from kfp.v2.dsl import Artifact
from kfp.v2.dsl import Input
from kfp.v2.dsl import Output

import config as config

@dsl.component(
    base_image=config.ALPHAFOLD_COMPONENTS_IMAGE,
    packages_to_install=['google-cloud-storage']
)
def predict(
    model_features: Input[Artifact],
    model_params: Input[Artifact],
    model_name: str,
    prediction_index: int,
    num_ensemble: int,
    run_multimer_system: bool,
    random_seed: int,
    tf_force_unified_memory: str,
    xla_python_client_mem_fraction: str,
    raw_prediction: Output[Artifact],
    unrelaxed_protein: Output[Artifact]
):
  """Configures and runs AlphaFold model runner."""

  import logging
  import time
  import os
  from google.cloud import storage
  import tempfile

  from alphafold_utils import predict as alphafold_predict

  os.environ['TF_FORCE_UNIFIED_MEMORY'] = tf_force_unified_memory
  os.environ['XLA_PYTHON_CLIENT_MEM_FRACTION'] = xla_python_client_mem_fraction

  logging.info(f'Starting model prediction {prediction_index} using model {model_name}...')
  t0 = time.time()
  
  random_seed = int(random_seed)
  # Download model features from GCS if it's a GCS path
  if model_features.uri.startswith('gs://'):
    storage_client = storage.Client()
    bucket_name = model_features.uri.replace('gs://', '').split('/')[0]
    blob_path = '/'.join(model_features.uri.replace('gs://', '').split('/')[1:])
        
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_path)
        
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        blob.download_to_filename(temp_file.name)
        model_features_path = temp_file.name
        logging.info(f'Downloaded model features to temporary file: {model_features_path}')
  else:
    model_features_path = model_features.path

  raw_prediction.uri = f'{raw_prediction.uri}.pkl'
  unrelaxed_protein.uri = f'{unrelaxed_protein.uri}.pdb'
  prediction_result = alphafold_predict(
      model_features_path=model_features_path,
      model_params_path=model_params.path,
      model_name=model_name,
      num_ensemble=num_ensemble,
      run_multimer_system=run_multimer_system,
      random_seed=random_seed,
      raw_prediction_path=raw_prediction.path,
      unrelaxed_protein_path=unrelaxed_protein.path
  )

  raw_prediction.metadata['category'] = 'raw_prediction'
  raw_prediction.metadata['prediction_index'] = prediction_index
  raw_prediction.metadata['ranking_confidence'] = prediction_result[
      'ranking_confidence']
  unrelaxed_protein.metadata['category'] = 'unrelaxed_protein'

  t1 = time.time()
  logging.info(f'Model prediction completed. Elapsed time: {t1-t0}')
