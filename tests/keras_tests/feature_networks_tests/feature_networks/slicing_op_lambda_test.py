# Copyright 2021 Sony Semiconductors Israel, Inc. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
import tensorflow as tf

if tf.__version__ < "2.6":
    from tensorflow.python.keras.layers.core import SlicingOpLambda
else:
    from keras.layers.core import SlicingOpLambda

from tests.keras_tests.feature_networks_tests.base_feature_test import BaseFeatureNetworkTest
import model_compression_toolkit as mct

import numpy as np
from tests.common_tests.helpers.tensors_compare import cosine_similarity

keras = tf.keras
layers = keras.layers


class SlicingOpLambdaTest(BaseFeatureNetworkTest):
    def __init__(self, unit_test):
        super().__init__(unit_test, val_batch_size=1)

    def get_quantization_config(self):
        return mct.QuantizationConfig(mct.ThresholdSelectionMethod.MSE,
                                      mct.ThresholdSelectionMethod.MSE,
                                      mct.QuantizationMethod.POWER_OF_TWO,
                                      mct.QuantizationMethod.POWER_OF_TWO,
                                      16,
                                      16,
                                      False,
                                      False,
                                      True)


    def create_feature_network(self, input_shape):
        inputs = layers.Input(shape=input_shape[0][1:])
        outputs = tf.add(inputs[0:], inputs[0:])
        return keras.Model(inputs=inputs, outputs=outputs)

    def compare(self, quantized_model, float_model, input_x=None, quantization_info=None):
        self.unit_test.assertTrue(quantized_model.layers[4].function == tf.add)
        self.unit_test.assertTrue(quantized_model.layers[4].outbound_nodes[0].layer.function == tf.quantization.fake_quant_with_min_max_vars)
        self.unit_test.assertTrue(isinstance(quantized_model.layers[2], SlicingOpLambda))
        self.unit_test.assertTrue(isinstance(quantized_model.layers[3], SlicingOpLambda))
        y = float_model.predict(input_x)
        y_hat = quantized_model.predict(input_x)
        cs = cosine_similarity(y, y_hat)
        self.unit_test.assertTrue(np.isclose(cs, 1), msg=f'fail cosine similarity check:{cs}')