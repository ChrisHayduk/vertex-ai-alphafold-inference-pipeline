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
"""A component encapsulating hmmsearch tool."""

from kfp.v2 import dsl
from kfp.v2.dsl import Artifact
from kfp.v2.dsl import Input
from kfp.v2.dsl import Output

import config as config


@dsl.component(
    base_image=config.ALPHAFOLD_COMPONENTS_IMAGE
)
def hmmsearch(
    sequence: Input[Artifact],
    ref_databases: Input[Artifact],
    msa: Input[Artifact],
    template_db: str,
    mmcif_db: str,
    obsolete_db: str,
    max_template_date: str,
    template_hits: Output[Artifact],
    template_features: Output[Artifact],
    max_template_hits: int = 20,
):
  """Configures and runs hmmsearch."""

  import logging
  import os
  import time

  from alphafold_utils import run_hmmsearch

  logging.info('Starting hmmsearch search')
  t0 = time.time()

  mount_path = ref_databases.uri

  msa, features = run_hmmsearch(
      sequence_path=sequence.path,
      msa_path=msa.path,
      msa_data_format=msa.metadata['data_format'],
      template_db_path=os.path.join(
          mount_path, ref_databases.metadata[template_db]),
      mmcif_path=os.path.join(
          mount_path, ref_databases.metadata[mmcif_db]),
      obsolete_path=os.path.join(
          mount_path, ref_databases.metadata[obsolete_db]),
      max_template_date=max_template_date,
      max_template_hits=max_template_hits,
      template_hits_path=template_hits.path,
      template_features_path=template_features.path
  )

  template_hits.metadata['category'] = 'msa'
  template_hits.metadata['num_hits'] = len(msa)
  template_hits.metadata['data_format'] = 'sto'
  template_hits.metadata['tool'] = 'hmmearch'
  template_features.metadata['category'] = 'features'
  template_features.metadata['data_format'] = 'pkl'

  t1 = time.time()
  logging.info(f'Hhsearch search completed. Elapsed time: {t1-t0}')