# Copyright 2022 Sony Semiconductor Israel, Inc. All rights reserved.
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
from typing import Dict

import numpy as np
import torch
import torch.nn as nn

from model_compression_toolkit.core.common.target_platform import QuantizationMethod
from model_compression_toolkit.qat.common import THRESHOLD_TENSOR
from model_compression_toolkit import quantizers_infrastructure as qi
from model_compression_toolkit.core.common import constants as C
from model_compression_toolkit.core.pytorch.utils import to_torch_tensor
from model_compression_toolkit.qat.pytorch.quantizer.quantizer_utils import ste_round, ste_clip, symmetric_quantizer
from model_compression_toolkit.quantizers_infrastructure.common.base_trainable_quantizer_config import \
    TrainableQuantizerWeightsConfig, TrainableQuantizerActivationConfig


class STEWeightQuantizer(qi.BasePytorchTrainableQuantizer):
    """
    Trainable constrained quantizer to quantize a layer weights.
    """

    def __init__(self, quantization_config: TrainableQuantizerWeightsConfig):
        """
        Initialize a TrainableWeightQuantizer object with parameters to use
        for the quantization.

        Args:
            quantization_config: trainable quantizer config class
        """
        super().__init__(quantization_config,
                         qi.QuantizationTarget.Weights,
                         [qi.QuantizationMethod.POWER_OF_TWO, qi.QuantizationMethod.SYMMETRIC])
        self.power_of_two = quantization_config.weights_quantization_method == QuantizationMethod.POWER_OF_TWO
        self.threshold_values = quantization_config.weights_quantization_params[C.THRESHOLD]
        self.threshold_shape = np.asarray(self.threshold_values).shape
        self.np_threshold_values = self.threshold_values

        if self.power_of_two:
            self.np_threshold_values = np.power(2.0,
                                                np.ceil(np.log2(np.maximum(self.np_threshold_values, C.MIN_THRESHOLD))))
        num_bits = self.quantization_config.weights_n_bits
        delta = self.np_threshold_values / np.power(2.0, num_bits - int(C.WEIGHTS_SIGNED))
        self.delta_tensor = to_torch_tensor(delta)
        self.min_int = -int(C.WEIGHTS_SIGNED) * (2 ** (num_bits - int(C.WEIGHTS_SIGNED)))
        self.max_int = (2 ** (num_bits - int(C.WEIGHTS_SIGNED))) - 1
        self.min = delta * self.min_int
        self.max = delta * self.max_int
        self.quantizer_parameters = {}

    def initialize_quantization(self,
                                tensor_shape: torch.Size,
                                name: str,
                                layer: qi.PytorchQuantizationWrapper) -> Dict[str, nn.Parameter]:
        """
        Add min and max variables to layer.
        Args:
            tensor_shape: Tensor shape the quantizer quantize.
            name: Prefix of variables names.
            layer: Layer to add the variables to. The variables are saved
            in the layer's scope.

        Returns:
            Dictionary of new variables.
        """

        # Add threshold variables to layer.
        layer.register_parameter(name + "_" + THRESHOLD_TENSOR, nn.Parameter(to_torch_tensor(self.np_threshold_values), requires_grad=False))

        # save the quantizer added parameters for later calculations
        self.quantizer_parameters = {THRESHOLD_TENSOR: layer.get_parameter(name + "_" + THRESHOLD_TENSOR)}

        return self.quantizer_parameters

    def __call__(self,
                 inputs: nn.Parameter,
                 training: bool) -> nn.Parameter:
        """
        Quantize a tensor
        Args:
            inputs: Input tensor to quantize.
            training: whether in training mode or not
        Returns:
            quantized tensor
        """
        w0 = ste_round(inputs / self.delta_tensor)
        w1 = ste_clip(w0, min_val=self.min_int, max_val=self.max_int)
        w_q = self.delta_tensor * w1
        return w_q


class STEActivationQuantizer(qi.BasePytorchTrainableQuantizer):
    """
    Trainable constrained quantizer to quantize a layer activations.
    """

    def __init__(self, quantization_config: TrainableQuantizerActivationConfig):
        """
        Initialize a STEActivationQuantizer object with parameters to use
        for symmetric or power of two quantization.

        Args:
            quantization_config: trainable quantizer config class
        """
        super().__init__(quantization_config,
                         qi.QuantizationTarget.Activation,
                         [qi.QuantizationMethod.POWER_OF_TWO, qi.QuantizationMethod.SYMMETRIC])
        self.power_of_two = quantization_config.activation_quantization_method == QuantizationMethod.POWER_OF_TWO
        self.sign = quantization_config.activation_quantization_params['is_signed']
        np_threshold_values = quantization_config.activation_quantization_params[C.THRESHOLD]
        self.threshold_tensor = torch.Tensor([np_threshold_values])
        self.num_bits = quantization_config.activation_n_bits
        self.quantizer_parameters = {}

    def initialize_quantization(self,
                                tensor_shape: torch.Size,
                                name: str,
                                layer: qi.PytorchQuantizationWrapper) -> Dict[str, nn.Parameter]:
        """
        Add threshold variables to layer.
        """
        layer.register_parameter(name, nn.Parameter(to_torch_tensor(self.threshold_tensor), requires_grad=True))

        # save the quantizer added parameters for later calculations
        self.quantizer_parameters = {THRESHOLD_TENSOR: layer.get_parameter(name)}
        return self.quantizer_parameters

    def __call__(self,
                 inputs: torch.Tensor,
                 training: bool = True) -> torch.Tensor:
        """
        Quantize a tensor.
        Args:
            inputs: Input tensor to quantize.
            training: Whether the graph is in training mode.

        Returns:
            The quantized tensor.
        """

        _t = self.quantizer_parameters[THRESHOLD_TENSOR]
        q_tensor = symmetric_quantizer(inputs, _t, self.num_bits, sign=self.sign)
        return q_tensor