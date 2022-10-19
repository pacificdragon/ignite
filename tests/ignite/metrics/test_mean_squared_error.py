import os

import numpy as np
import pytest
import torch

import ignite.distributed as idist
from ignite.exceptions import NotComputableError
from ignite.metrics import MeanSquaredError


def test_zero_sample():
    mse = MeanSquaredError()
    with pytest.raises(
        NotComputableError, match=r"MeanSquaredError must have at least one example before it can be computed"
    ):
        mse.compute()


@pytest.fixture(params=[item for item in range(4)])
def test_case(request):
    return [
        (torch.randint(0, 10, size=(100, 1)), torch.randint(0, 10, size=(100, 1)), 1),
        (torch.randint(-20, 20, size=(100, 5)), torch.randint(-20, 20, size=(100, 5)), 1),
        # updated batches
        (torch.randint(0, 10, size=(100, 1)), torch.randint(0, 10, size=(100, 1)), 16),
        (torch.randint(-20, 20, size=(100, 5)), torch.randint(-20, 20, size=(100, 5)), 16),
    ][request.param]


@pytest.mark.parametrize("n_times", range(5))
def test_compute(n_times, test_case):

    mse = MeanSquaredError()

    y_pred, y, batch_size = test_case

    mse.reset()
    if batch_size > 1:
        n_iters = y.shape[0] // batch_size + 1
        for i in range(n_iters):
            idx = i * batch_size
            mse.update((y_pred[idx : idx + batch_size], y[idx : idx + batch_size]))
    else:
        mse.update((y_pred, y))

    np_y = y.numpy()
    np_y_pred = y_pred.numpy()

    np_res = np.power((np_y - np_y_pred), 2.0).sum() / np_y.shape[0]

    assert isinstance(mse.compute(), float)
    assert mse.compute() == np_res


def _test_distrib_integration(device, tol=1e-6):

    from ignite.engine import Engine

    rank = idist.get_rank()
    torch.manual_seed(12 + rank)

    def _test(metric_device):
        n_iters = 100
        batch_size = 10

        y_true = torch.arange(0, n_iters * batch_size, dtype=torch.float).to(device)
        y_preds = torch.ones(n_iters * batch_size, dtype=torch.float).to(device)

        def update(engine, i):
            return (
                y_preds[i * batch_size : (i + 1) * batch_size],
                y_true[i * batch_size : (i + 1) * batch_size],
            )

        engine = Engine(update)

        m = MeanSquaredError(device=metric_device)
        m.attach(engine, "mse")

        data = list(range(n_iters))
        engine.run(data=data, max_epochs=1)

        y_preds = idist.all_gather(y_preds)
        y_true = idist.all_gather(y_true)

        assert "mse" in engine.state.metrics
        res = engine.state.metrics["mse"]

        true_res = np.mean(np.power((y_true - y_preds).cpu().numpy(), 2.0))

        assert pytest.approx(res, rel=tol) == true_res

    _test("cpu")
    if device.type != "xla":
        _test(idist.device())


def _test_distrib_accumulator_device(device):

    metric_devices = [torch.device("cpu")]
    if device.type != "xla":
        metric_devices.append(idist.device())
    for metric_device in metric_devices:

        device = torch.device(device)
        mse = MeanSquaredError(device=metric_device)

        for dev in [mse._device, mse._sum_of_squared_errors.device]:
            assert dev == metric_device, f"{type(dev)}:{dev} vs {type(metric_device)}:{metric_device}"

        y_pred = torch.tensor([[2.0], [-2.0]])
        y = torch.zeros(2)
        mse.update((y_pred, y))

        for dev in [mse._device, mse._sum_of_squared_errors.device]:
            assert dev == metric_device, f"{type(dev)}:{dev} vs {type(metric_device)}:{metric_device}"


def test_accumulator_detached():
    mse = MeanSquaredError()

    y_pred = torch.tensor([[2.0], [-2.0]], requires_grad=True)
    y = torch.zeros(2)
    mse.update((y_pred, y))

    assert not mse._sum_of_squared_errors.requires_grad


@pytest.mark.distributed
@pytest.mark.skipif(not idist.has_native_dist_support, reason="Skip if no native dist support")
@pytest.mark.skipif(torch.cuda.device_count() < 1, reason="Skip if no GPU")
def test_distrib_nccl_gpu(distributed_context_single_node_nccl):

    device = idist.device()
    _test_distrib_integration(device)
    _test_distrib_accumulator_device(device)


@pytest.mark.distributed
@pytest.mark.skipif(not idist.has_native_dist_support, reason="Skip if no native dist support")
def test_distrib_gloo_cpu_or_gpu(distributed_context_single_node_gloo):

    device = idist.device()
    _test_distrib_integration(device)
    _test_distrib_accumulator_device(device)


@pytest.mark.distributed
@pytest.mark.skipif(not idist.has_hvd_support, reason="Skip if no Horovod dist support")
@pytest.mark.skipif("WORLD_SIZE" in os.environ, reason="Skip if launched as multiproc")
def test_distrib_hvd(gloo_hvd_executor):

    device = torch.device("cpu" if not torch.cuda.is_available() else "cuda")
    nproc = 4 if not torch.cuda.is_available() else torch.cuda.device_count()

    gloo_hvd_executor(_test_distrib_integration, (device,), np=nproc, do_init=True)
    gloo_hvd_executor(_test_distrib_accumulator_device, (device,), np=nproc, do_init=True)


@pytest.mark.multinode_distributed
@pytest.mark.skipif(not idist.has_native_dist_support, reason="Skip if no native dist support")
@pytest.mark.skipif("MULTINODE_DISTRIB" not in os.environ, reason="Skip if not multi-node distributed")
def test_multinode_distrib_gloo_cpu_or_gpu(distributed_context_multi_node_gloo):

    device = idist.device()
    _test_distrib_integration(device)
    _test_distrib_accumulator_device(device)


@pytest.mark.multinode_distributed
@pytest.mark.skipif(not idist.has_native_dist_support, reason="Skip if no native dist support")
@pytest.mark.skipif("GPU_MULTINODE_DISTRIB" not in os.environ, reason="Skip if not multi-node distributed")
def test_multinode_distrib_nccl_gpu(distributed_context_multi_node_nccl):

    device = idist.device()
    _test_distrib_integration(device)
    _test_distrib_accumulator_device(device)


@pytest.mark.tpu
@pytest.mark.skipif("NUM_TPU_WORKERS" in os.environ, reason="Skip if NUM_TPU_WORKERS is in env vars")
@pytest.mark.skipif(not idist.has_xla_support, reason="Skip if no PyTorch XLA package")
def test_distrib_single_device_xla():
    device = idist.device()
    _test_distrib_integration(device, tol=1e-4)
    _test_distrib_accumulator_device(device)


def _test_distrib_xla_nprocs(index):
    device = idist.device()
    _test_distrib_integration(device, tol=1e-4)
    _test_distrib_accumulator_device(device)


@pytest.mark.tpu
@pytest.mark.skipif("NUM_TPU_WORKERS" not in os.environ, reason="Skip if no NUM_TPU_WORKERS in env vars")
@pytest.mark.skipif(not idist.has_xla_support, reason="Skip if no PyTorch XLA package")
def test_distrib_xla_nprocs(xmp_executor):
    n = int(os.environ["NUM_TPU_WORKERS"])
    xmp_executor(_test_distrib_xla_nprocs, args=(), nprocs=n)
