from typing import Callable, Union

import torch

from ignite.contrib.metrics.regression._base import _torch_median

from ignite.metrics import EpochMetric


def median_absolute_error_compute_fn(y_pred: torch.Tensor, y: torch.Tensor) -> float:
    e = torch.abs(y.view_as(y_pred) - y_pred)
    return _torch_median(e)


class MedianAbsoluteError(EpochMetric):
    r"""Calculates the Median Absolute Error.

    .. math::
        \text{MdAE} = \text{MD}_{j=1,n} \left( |A_j - P_j| \right)

    where :math:`A_j` is the ground truth and :math:`P_j` is the predicted value.

    More details can be found in `Botchkarev 2018`__.

    - ``update`` must receive output of the form ``(y_pred, y)`` or ``{'y_pred': y_pred, 'y': y}``.
    - `y` and `y_pred` must be of same shape `(N, )` or `(N, 1)` and of type `float32`.

    .. warning::

        Current implementation stores all input data (output and target) in as tensors before computing a metric.
        This can potentially lead to a memory error if the input data is larger than available RAM.


    __ https://arxiv.org/abs/1809.03006

    Args:
        output_transform: a callable that is used to transform the
            :class:`~ignite.engine.engine.Engine`'s ``process_function``'s output into the
            form expected by the metric. This can be useful if, for example, you have a multi-output model and
            you want to compute the metric with respect to one of the outputs.
            By default, metrics require the output as ``(y_pred, y)`` or ``{'y_pred': y_pred, 'y': y}``.
        device: optional device specification for internal storage.


    Examples:
        To use with ``Engine`` and ``process_function``, simply attach the metric instance to the engine.
        The output of the engine's ``process_function`` needs to be in format of
        ``(y_pred, y)`` or ``{'y_pred': y_pred, 'y': y, ...}``.

        .. include:: defaults.rst
            :start-after: :orphan:

        .. testcode::

            metric = MedianAbsoluteError()
            metric.attach(default_evaluator, 'mae')
            y_true = torch.tensor([0, 1, 2, 3, 4, 5])
            y_pred = y_true * 0.75
            state = default_evaluator.run([[y_pred, y_true]])
            print(state.metrics['mae'])

        .. testoutput::

            0.625
    """

    def __init__(
        self, output_transform: Callable = lambda x: x, device: Union[str, torch.device] = torch.device("cpu")
    ):

        super(MedianAbsoluteError, self).__init__(
            median_absolute_error_compute_fn, output_transform=output_transform, device=device
        )
