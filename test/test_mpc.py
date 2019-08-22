#!/usr/bin/env python3

import itertools

# dependencies:
import logging
import math
import unittest
from test.multiprocess_test_case import MultiProcessTestCase, get_random_test_tensor

import torch
import torch.nn.functional as F


# placeholders for class references, to be filled later by import_crypten():
MPCTensor, is_float_tensor = None, None


def import_crypten():
    """
    Imports CrypTen types. This function is called after environment variables
    in MultiProcessTestCase.setUp() are set, and sets the class references for
    all test functions.
    """
    global MPCTensor, is_float_tensor
    from crypten import MPCTensor as _MPCTensor
    from crypten.common.tensor_types import is_float_tensor as _is_float_tensor

    MPCTensor = _MPCTensor
    is_float_tensor = _is_float_tensor


class TestMPC(MultiProcessTestCase):
    """
        This class tests all functions of the SPDZ tensors.
    """

    benchmarks_enabled = False

    def setUp(self):
        super().setUp()
        # We don't want the main process (rank -1) to initialize the communcator
        if self.rank >= 0:
            import_crypten()

    def _check(self, encrypted_tensor, reference, msg, tolerance=None):
        if tolerance is None:
            tolerance = getattr(self, "default_tolerance", 0.05)
        tensor = encrypted_tensor.get_plain_text()

        if self.rank != 0:  # Do not check for non-0 rank
            return

        # Check sizes match
        self.assertTrue(tensor.size() == reference.size(), msg)

        self.assertTrue(is_float_tensor(reference), "reference must be a float")
        diff = (tensor - reference).abs_()
        norm_diff = diff.div(tensor.abs() + reference.abs()).abs_()
        test_passed = norm_diff.le(tolerance) + diff.le(tolerance * 0.1)
        test_passed = test_passed.gt(0).all().item() == 1
        if not test_passed:
            logging.info(msg)
            logging.info("Result = %s;\nreference = %s" % (tensor, reference))
        self.assertTrue(test_passed, msg=msg)

    def test_encrypt_decrypt(self):
        """
            Tests tensor encryption and decryption for both positive
            and negative values.
        """
        sizes = [
            (),
            (1,),
            (5,),
            (1, 1),
            (1, 5),
            (5, 1),
            (5, 5),
            (1, 5, 5),
            (5, 1, 5),
            (5, 5, 1),
            (5, 5, 5),
            (1, 3, 32, 32),
            (5, 3, 32, 32),
        ]
        for size in sizes:
            reference = get_random_test_tensor(size=size, is_float=True)
            with self.benchmark(tensor_type="MPCTensor") as bench:
                for _ in bench.iters:
                    encrypted_tensor = MPCTensor(reference)
                    self._check(encrypted_tensor, reference, "en/decryption failed")

    def test_arithmetic(self):
        """Tests arithmetic functions on encrypted tensor."""
        arithmetic_functions = ["add", "add_", "sub", "sub_", "mul", "mul_"]
        for func in arithmetic_functions:
            for tensor_type in [lambda x: x, MPCTensor]:
                tensor1 = get_random_test_tensor(is_float=True)
                tensor2 = get_random_test_tensor(is_float=True)
                encrypted = MPCTensor(tensor1)
                encrypted2 = tensor_type(tensor2)

                reference = getattr(tensor1, func)(tensor2)
                encrypted_out = getattr(encrypted, func)(encrypted2)
                self._check(
                    encrypted_out,
                    reference,
                    "%s %s failed"
                    % ("private" if tensor_type == MPCTensor else "public", func),
                )
                if "_" in func:
                    # Check in-place op worked
                    self._check(
                        encrypted,
                        reference,
                        "%s %s failed"
                        % ("private" if tensor_type == MPCTensor else "public", func),
                    )
                else:
                    # Check original is not modified
                    self._check(
                        encrypted,
                        tensor1,
                        "%s %s failed"
                        % ("private" if tensor_type == MPCTensor else "public", func),
                    )

                # Check encrypted vector with encrypted scalar works.
                tensor1 = get_random_test_tensor(is_float=True)
                tensor2 = get_random_test_tensor(is_float=True, size=(1,))
                encrypted1 = MPCTensor(tensor1)
                encrypted2 = MPCTensor(tensor2)
                reference = getattr(tensor1, func)(tensor2)
                encrypted_out = getattr(encrypted1, func)(encrypted2)
                self._check(encrypted_out, reference, "private %s failed" % func)

            tensor = get_random_test_tensor(is_float=True)
            reference = tensor * tensor
            encrypted = MPCTensor(tensor)
            encrypted_out = encrypted.square()
            self._check(encrypted_out, reference, "square failed")

        # Test radd, rsub, and rmul
        reference = 2 + tensor1
        encrypted = MPCTensor(tensor1)
        encrypted_out = 2 + encrypted
        self._check(encrypted_out, reference, "right add failed")

        reference = 2 - tensor1
        encrypted_out = 2 - encrypted
        self._check(encrypted_out, reference, "right sub failed")

        reference = 2 * tensor1
        encrypted_out = 2 * encrypted
        self._check(encrypted_out, reference, "right mul failed")

    def test_sum(self):
        tensor = get_random_test_tensor(size=(100, 100), is_float=True)
        encrypted = MPCTensor(tensor)
        self._check(encrypted.sum(), tensor.sum(), "sum failed")

        for dim in [0, 1]:
            reference = tensor.sum(dim)
            with self.benchmark(type="sum", float=float, dim=dim) as bench:
                for _ in bench.iters:
                    encrypted_out = encrypted.sum(dim)
            self._check(encrypted_out, reference, "sum failed")

    def test_div(self):
        """Tests division of encrypted tensor by scalar."""
        for function in ["div", "div_"]:
            for scalar in [2, 2.0]:
                tensor = get_random_test_tensor(is_float=True)

                reference = tensor.float().div(scalar)
                encrypted_tensor = MPCTensor(tensor)
                encrypted_tensor = getattr(encrypted_tensor, function)(scalar)
                self._check(encrypted_tensor, reference, "division failed")

                divisor = get_random_test_tensor(is_float=float)
                divisor += (divisor == 0).to(dtype=divisor.dtype)  # div by 0

                reference = tensor.div(divisor)
                encrypted_tensor = MPCTensor(tensor)
                encrypted_tensor = getattr(encrypted_tensor, function)(divisor)
                self._check(encrypted_tensor, reference, "division failed")

    def test_mean(self):
        """Tests computing means of encrypted tensors."""
        tensor = get_random_test_tensor(size=(5, 10, 15), is_float=True)
        encrypted = MPCTensor(tensor)
        self._check(encrypted.mean(), tensor.mean(), "mean failed")

        for dim in [0, 1, 2]:
            reference = tensor.mean(dim)
            encrypted_out = encrypted.mean(dim)
            self._check(encrypted_out, reference, "mean failed")

    def test_matmul(self):
        """Test matrix multiplication."""
        for tensor_type in [lambda x: x, MPCTensor]:
            tensor = get_random_test_tensor(max_value=7, is_float=True)
            for width in range(2, tensor.nelement()):
                matrix_size = (tensor.nelement(), width)
                matrix = get_random_test_tensor(
                    max_value=7, size=matrix_size, is_float=True
                )
                reference = tensor.matmul(matrix)
                encrypted_tensor = MPCTensor(tensor)
                matrix = tensor_type(matrix)
                encrypted_tensor = encrypted_tensor.matmul(matrix)

                self._check(
                    encrypted_tensor,
                    reference,
                    "Private-%s matrix multiplication failed"
                    % ("private" if tensor_type == MPCTensor else "public"),
                )

    def test_dot_ger(self):
        """Test dot product of vector and encrypted tensor."""
        for tensor_type in [lambda x: x, MPCTensor]:
            tensor1 = get_random_test_tensor(is_float=True).squeeze()
            tensor2 = get_random_test_tensor(is_float=True).squeeze()
            dot_reference = tensor1.dot(tensor2)
            ger_reference = torch.ger(tensor1, tensor2)

            tensor2 = tensor_type(tensor2)

            # dot
            encrypted_tensor = MPCTensor(tensor1)
            encrypted_out = encrypted_tensor.dot(tensor2)
            self._check(
                encrypted_out,
                dot_reference,
                "%s dot product failed" % "private"
                if tensor_type == MPCTensor
                else "public",
            )

            # ger
            encrypted_tensor = MPCTensor(tensor1)
            encrypted_out = encrypted_tensor.ger(tensor2)
            self._check(
                encrypted_out,
                ger_reference,
                "%s outer product failed" % "private"
                if tensor_type == MPCTensor
                else "public",
            )

    def test_squeeze(self):
        tensor = get_random_test_tensor(is_float=True)
        for dim in [0, 1, 2]:
            # Test unsqueeze
            reference = tensor.unsqueeze(dim)

            encrypted = MPCTensor(tensor)
            with self.benchmark(type="unsqueeze", dim=dim) as bench:
                for _ in bench.iters:
                    encrypted_out = encrypted.unsqueeze(dim)
            self._check(encrypted_out, reference, "unsqueeze failed")

            # Test squeeze
            encrypted = MPCTensor(tensor.unsqueeze(0))
            with self.benchmark(type="squeeze", dim=dim) as bench:
                for _ in bench.iters:
                    encrypted_out = encrypted.squeeze()
            self._check(encrypted_out, reference.squeeze(), "squeeze failed")

            # Check that the encrypted_out and encrypted point to the same
            # thing.
            encrypted_out[0:2] = torch.FloatTensor([0, 1])
            ref = encrypted.squeeze().get_plain_text()
            self._check(encrypted_out, ref, "squeeze failed")

    def test_transpose(self):
        sizes = [
            (1,),
            (5,),
            (1, 1),
            (1, 5),
            (5, 1),
            (5, 5),
            (1, 5, 5),
            (5, 1, 5),
            (5, 5, 1),
            (5, 5, 5),
            (1, 3, 32, 32),
            (5, 3, 32, 32),
        ]
        for size in sizes:
            tensor = get_random_test_tensor(size=size, is_float=True)
            encrypted_tensor = MPCTensor(tensor)

            if len(size) == 2:  # t() asserts dim == 2
                reference = tensor.t()
                with self.benchmark(niters=10) as bench:
                    for _ in bench.iters:
                        encrypted_out = encrypted_tensor.t()
                self._check(encrypted_out, reference, "t() failed")

            for dim0 in range(len(size)):
                for dim1 in range(len(size)):
                    reference = tensor.transpose(dim0, dim1)
                    with self.benchmark(niters=10) as bench:
                        for _ in bench.iters:
                            encrypted_out = encrypted_tensor.transpose(dim0, dim1)
                    self._check(encrypted_out, reference, "transpose failed")

    def test_conv(self):
        """Test convolution of encrypted tensor with public/private tensors."""
        for kernel_type in [lambda x: x, MPCTensor]:
            for matrix_width in range(2, 5):
                for kernel_width in range(1, matrix_width):
                    for padding in range(kernel_width // 2 + 1):
                        matrix_size = (5, matrix_width)
                        matrix = get_random_test_tensor(size=matrix_size, is_float=True)

                        kernel_size = (kernel_width, kernel_width)
                        kernel = get_random_test_tensor(size=kernel_size, is_float=True)

                        matrix = matrix.unsqueeze(0).unsqueeze(0)
                        kernel = kernel.unsqueeze(0).unsqueeze(0)

                        reference = F.conv2d(matrix, kernel, padding=padding)
                        encrypted_matrix = MPCTensor(matrix)
                        encrypted_kernel = kernel_type(kernel)
                        with self.benchmark(
                            kernel_type=kernel_type.__name__, matrix_width=matrix_width
                        ) as bench:
                            for _ in bench.iters:
                                encrypted_conv = encrypted_matrix.conv2d(
                                    encrypted_kernel, padding=padding
                                )

                        self._check(encrypted_conv, reference, "conv2d failed")

    def test_pooling(self):
        """Test avg_pool, sum_pool, max_pool of encrypted tensor."""
        for func in ["avg_pool2d", "sum_pool2d", "max_pool2d"]:
            for width in range(2, 5):
                for width2 in range(1, width):
                    matrix_size = (1, 4, 5, width)
                    matrix = get_random_test_tensor(size=matrix_size, is_float=True)
                    pool_size = width2
                    for stride in range(1, width2):
                        for padding in range(2):
                            if func == "max_pool2d":
                                reference = F.max_pool2d(
                                    matrix, pool_size, stride=stride, padding=padding
                                )
                            else:
                                reference = F.avg_pool2d(
                                    matrix, pool_size, stride=stride, padding=padding
                                )
                                if func == "sum_pool2d":
                                    reference *= width2 * width2

                            encrypted_matrix = MPCTensor(matrix)
                            with self.benchmark(func=func, width=width) as bench:
                                for _ in bench.iters:
                                    encrypted_pool = getattr(encrypted_matrix, func)(
                                        pool_size, stride=stride, padding=padding
                                    )
                            self._check(encrypted_pool, reference, "%s failed" % func)

    def test_relu(self):
        """Test relu on encrypted tensor."""
        for width in range(2, 5):
            matrix_size = (5, width)
            matrix = get_random_test_tensor(size=matrix_size, is_float=True)

            # Generate some negative values
            matrix2 = get_random_test_tensor(size=matrix_size, is_float=True)
            matrix = matrix - matrix2

            encrypted_matrix = MPCTensor(matrix)
            reference = F.relu_(matrix)
            with self.benchmark(float=float, width=width, boolean=True) as bench:
                for _ in bench.iters:
                    encrypted_matrix = encrypted_matrix.relu()
            self._check(encrypted_matrix, reference, "relu failed")

    def test_comparators(self):
        """Test comparators (>, >=, <, <=, ==, !=)"""
        for comp in ["gt", "ge", "lt", "le", "eq", "ne"]:
            for tensor_type in [lambda x: x, MPCTensor]:
                tensor = get_random_test_tensor(is_float=True)
                tensor2 = get_random_test_tensor(is_float=True)

                encrypted_tensor = MPCTensor(tensor)
                encrypted_tensor2 = tensor_type(tensor2)

                reference = getattr(tensor, comp)(tensor2).float()

                with self.benchmark(comp=comp) as bench:
                    for _ in bench.iters:
                        encrypted_out = getattr(encrypted_tensor, comp)(
                            encrypted_tensor2
                        )

                self._check(encrypted_out, reference, "%s comparator failed" % comp)

    def test_max_min(self):
        """Test max and min"""
        sizes = [
            (),
            (1,),
            (5,),
            (1, 1),
            (1, 5),
            (5, 5),
            (5, 1),
            (1, 1, 1),
            (1, 5, 1),
            (1, 1, 5),
            (1, 5, 5),
            (5, 1, 1),
            (5, 5, 5),
            (1, 1, 1, 1),
            (5, 1, 1, 1),
            (5, 5, 1, 1),
            (1, 5, 5, 5),
            (5, 5, 5, 5),
        ]
        test_cases = [torch.FloatTensor([[1, 1, 2, 1, 4, 1, 3, 4]])] + [
            get_random_test_tensor(size=size, is_float=True) for size in sizes
        ]

        for tensor in test_cases:
            encrypted_tensor = MPCTensor(tensor)
            for comp in ["max", "min"]:
                reference = getattr(tensor, comp)()
                with self.benchmark(niters=10, comp=comp, dim=None) as bench:
                    for _ in bench.iters:
                        encrypted_out = getattr(encrypted_tensor, comp)()
                self._check(encrypted_out, reference, "%s reduction failed" % comp)

                for dim in range(tensor.dim()):
                    reference = getattr(tensor, comp)(dim=dim)[0]
                    with self.benchmark(niters=10, comp=comp, dim=dim) as bench:
                        for _ in bench.iters:
                            encrypted_out = getattr(encrypted_tensor, comp)(dim=dim)

                    self._check(encrypted_out, reference, "%s reduction failed" % comp)

    def test_argmax_argmin(self):
        """Test argmax and argmin"""
        sizes = [
            (),
            (1,),
            (5,),
            (1, 1),
            (1, 5),
            (5, 5),
            (5, 1),
            (1, 1, 1),
            (1, 5, 1),
            (1, 1, 5),
            (1, 5, 5),
            (5, 1, 1),
            (5, 5, 5),
            (1, 1, 1, 1),
            (5, 1, 1, 1),
            (5, 5, 1, 1),
            (1, 5, 5, 5),
            (5, 5, 5, 5),
        ]
        test_cases = [torch.FloatTensor([[1, 1, 2, 1, 4, 1, 3, 4]])] + [
            get_random_test_tensor(size=size, is_float=True) for size in sizes
        ]

        for tensor in test_cases:
            encrypted_tensor = MPCTensor(tensor)
            for comp in ["argmax", "argmin"]:
                cmp = comp[3:]

                # Compute one-hot argmax/min reference in plaintext
                values = getattr(tensor, cmp)()
                indices = (tensor == values).float()

                with self.benchmark(niters=10, comp=comp, dim=None) as bench:
                    for _ in bench.iters:
                        encrypted_out = getattr(encrypted_tensor, comp)()

                decrypted_out = encrypted_out.get_plain_text()
                self.assertTrue(decrypted_out.sum() == 1)
                self.assertTrue(decrypted_out.mul(indices).sum() == 1)

                for dim in range(tensor.dim()):
                    # Compute one-hot argmax/min reference in plaintext
                    values = getattr(tensor, cmp)(dim=dim)[0]
                    values = values.unsqueeze(dim)
                    indices = (tensor == values).float()

                    with self.benchmark(niters=10, comp=comp, dim=dim) as bench:
                        for _ in bench.iters:
                            encrypted_out = getattr(encrypted_tensor, comp)(dim=dim)
                    decrypted_out = encrypted_out.get_plain_text()
                    self.assertTrue((decrypted_out.sum(dim=dim) == 1).all())
                    self.assertTrue(
                        (decrypted_out.mul(indices).sum(dim=dim) == 1).all()
                    )

    def test_abs_sign(self):
        """Test absolute value function"""
        for op in ["abs", "sign"]:
            tensor = get_random_test_tensor(is_float=True)
            if op == "sign":
                # do not test on 0 since torch.tensor([0]).sign() = 0
                tensor = tensor + (tensor == 0).float()
            encrypted_tensor = MPCTensor(tensor)
            reference = getattr(tensor, op)()

            with self.benchmark(niters=10, op=op) as bench:
                for _ in bench.iters:
                    encrypted_out = getattr(encrypted_tensor, op)()

            self._check(encrypted_out, reference, "%s failed" % op)

    def test_approximations(self):
        """Test appoximate functions (exp, log, sqrt, reciprocal, pow)"""
        tensor = torch.tensor([0.01 * i for i in range(1, 1001, 1)])
        encrypted_tensor = MPCTensor(tensor)

        cases = ["exp", "log", "sqrt", "reciprocal"]
        for func in cases:
            reference = getattr(tensor, func)()
            with self.benchmark(niters=10, func=func) as bench:
                for _ in bench.iters:
                    encrypted_out = getattr(encrypted_tensor, func)()
            self._check(encrypted_out, reference, "%s failed" % func)

        for power in [-2, -1, -0.5, 0, 0.5, 1, 2]:
            reference = tensor.pow(power)
            with self.benchmark(niters=10, func="pow", power=power) as bench:
                for _ in bench.iters:
                    encrypted_out = encrypted_tensor.pow(power)
            self._check(encrypted_out, reference, "pow failed with %s power" % power)

    def test_norm(self):
        # Test 2-norm
        tensor = get_random_test_tensor(is_float=True)
        reference = tensor.norm()

        encrypted = MPCTensor(tensor)
        with self.benchmark() as bench:
            for _ in bench.iters:
                encrypted_out = encrypted.norm()
        self._check(encrypted_out, reference, "2-norm failed", tolerance=0.5)

    def test_logistic(self):
        tensor = torch.tensor([0.01 * i for i in range(-1000, 1001, 1)])
        encrypted_tensor = MPCTensor(tensor)

        cases = ["sigmoid", "tanh"]
        for func in cases:
            reference = getattr(tensor, func)()
            with self.benchmark(niters=10, func=func) as bench:
                for _ in bench.iters:
                    encrypted_out = getattr(encrypted_tensor, func)()
            self._check(encrypted_out, reference, "%s failed" % func)

    def test_cos_sin(self):
        tensor = torch.tensor([0.01 * i for i in range(-1000, 1001, 1)])
        encrypted_tensor = MPCTensor(tensor)

        cases = ["cos", "sin"]
        for func in cases:
            reference = getattr(tensor, func)()
            with self.benchmark(niters=10, func=func) as bench:
                for _ in bench.iters:
                    encrypted_out = getattr(encrypted_tensor, func)()
            self._check(encrypted_out, reference, "%s failed" % func)

    def test_rand(self):
        for size in [(10,), (10, 10), (10, 10, 10)]:
            with self.benchmark(size=size) as bench:
                for _ in bench.iters:
                    randvec = MPCTensor.rand(*size)
            self.assertTrue(randvec.size() == size, "Incorrect size")
            tensor = randvec.get_plain_text()
            self.assertTrue(
                (tensor >= 0).all() and (tensor < 1).all(), "Invalid values"
            )

        randvec = MPCTensor.rand(int(1e6)).get_plain_text()
        mean = torch.mean(randvec)
        var = torch.var(randvec)
        self.assertTrue(torch.isclose(mean, torch.Tensor([0.5]), rtol=1e-3, atol=1e-3))
        self.assertTrue(
            torch.isclose(var, torch.Tensor([1.0 / 12]), rtol=1e-3, atol=1e-3)
        )

    def test_bernoulli(self):
        for size in [(10,), (10, 10), (10, 10, 10)]:
            probs = torch.rand(size)
            with self.benchmark(size=size) as bench:
                for _ in bench.iters:
                    randvec = MPCTensor.bernoulli(probs)
            self.assertTrue(randvec.size() == size, "Incorrect size")
            tensor = randvec.get_plain_text()
            self.assertTrue(((tensor == 0) + (tensor == 1)).all(), "Invalid values")

        probs = torch.Tensor(int(1e6)).fill_(0.2)
        randvec = MPCTensor.bernoulli(probs).get_plain_text()
        frac_zero = float((randvec == 0).sum()) / randvec.nelement()
        self.assertTrue(math.isclose(frac_zero, 0.8, rel_tol=1e-3, abs_tol=1e-3))

    def test_softmax(self):
        """Test max function"""
        tensor = get_random_test_tensor(is_float=True)
        reference = torch.nn.functional.softmax(tensor, dim=1)

        encrypted_tensor = MPCTensor(tensor)
        with self.benchmark() as bench:
            for _ in bench.iters:
                encrypted_out = encrypted_tensor.softmax()
        self._check(encrypted_out, reference, "softmax failed")

    def test_get_set(self):
        for tensor_type in [lambda x: x, MPCTensor]:
            for size in range(1, 5):
                # Test __getitem__
                tensor = get_random_test_tensor(size=(size, size), is_float=True)
                reference = tensor[:, 0]

                encrypted_tensor = MPCTensor(tensor)
                encrypted_out = encrypted_tensor[:, 0]
                self._check(encrypted_out, reference, "getitem failed")

                reference = tensor[0, :]
                encrypted_out = encrypted_tensor[0, :]
                self._check(encrypted_out, reference, "getitem failed")

                # Test __setitem__
                tensor2 = get_random_test_tensor(size=(size,), is_float=True)
                reference = tensor.clone()
                reference[:, 0] = tensor2

                encrypted_out = MPCTensor(tensor)
                encrypted2 = tensor_type(tensor2)
                encrypted_out[:, 0] = encrypted2

                self._check(
                    encrypted_out, reference, "%s setitem failed" % type(encrypted2)
                )

                reference = tensor.clone()
                reference[0, :] = tensor2

                encrypted_out = MPCTensor(tensor)
                encrypted2 = tensor_type(tensor2)
                encrypted_out[0, :] = encrypted2

                self._check(
                    encrypted_out, reference, "%s setitem failed" % type(encrypted2)
                )

    def test_pad(self):
        sizes = [
            (1,),
            (5,),
            (1, 1),
            (5, 5),
            (5, 5, 5),
            (5, 3, 32, 32),
        ]
        pads = [
            (0, 0, 0, 0),
            (1, 0, 0, 0),
            (0, 1, 0, 0),
            (0, 0, 1, 0),
            (0, 0, 0, 1),
            (1, 1, 1, 1),
            (2, 2, 1, 1),
            (2, 2, 2, 2),
        ]

        for size in sizes:
            tensor = get_random_test_tensor(size=size, is_float=True)
            encrypted_tensor = MPCTensor(tensor)

            for pad in pads:
                for value in [0, 1, 10]:
                    for tensor_type in [lambda x: x, MPCTensor]:
                        if tensor.dim() < 2:
                            pad = pad[:2]
                        reference = torch.nn.functional.pad(tensor, pad, value=value)
                        encrypted_value = tensor_type(value)
                        with self.benchmark(tensor_type=tensor_type.__name__) as bench:
                            for _ in bench.iters:
                                encrypted_out = encrypted_tensor.pad(
                                    pad, value=encrypted_value
                                )
                        self._check(encrypted_out, reference, "pad failed")

    def test_broadcast(self):
        """Test broadcast functionality."""
        arithmetic_functions = ["add", "sub", "mul", "div"]
        arithmetic_sizes = [
            (),
            (1,),
            (2,),
            (1, 1),
            (1, 2),
            (2, 1),
            (2, 2),
            (1, 1, 1),
            (1, 1, 2),
            (1, 2, 1),
            (2, 1, 1),
            (2, 2, 2),
            (1, 1, 1, 1),
            (1, 1, 1, 2),
            (1, 1, 2, 1),
            (1, 2, 1, 1),
            (2, 1, 1, 1),
            (2, 2, 2, 2),
        ]
        matmul_sizes = [(1, 1), (1, 5), (5, 1), (5, 5)]
        batch_dims = [(), (1,), (5,), (1, 1), (1, 5), (5, 5)]

        for tensor_type in [lambda x: x, MPCTensor]:
            for func in arithmetic_functions:
                for size1, size2 in itertools.combinations(arithmetic_sizes, 2):
                    tensor1 = get_random_test_tensor(size=size1, is_float=True)
                    tensor2 = get_random_test_tensor(size=size2, is_float=True)
                    encrypted1 = MPCTensor(tensor1)
                    encrypted2 = tensor_type(tensor2)
                    reference = getattr(tensor1, func)(tensor2)
                    encrypted_out = getattr(encrypted1, func)(encrypted2)

                    private = isinstance(encrypted2, MPCTensor)
                    self._check(
                        encrypted_out,
                        reference,
                        "%s %s broadcast failed"
                        % ("private" if private else "public", func),
                    )

            for size in matmul_sizes:
                for batch1, batch2 in itertools.combinations(batch_dims, 2):
                    size1 = (*batch1, *size)
                    size2 = (*batch2, *size)

                    tensor1 = get_random_test_tensor(size=size1, is_float=True)
                    tensor2 = get_random_test_tensor(size=size2, is_float=True)
                    tensor2 = tensor1.transpose(-2, -1)

                    encrypted1 = MPCTensor(tensor1)
                    encrypted2 = tensor_type(tensor2)

                    reference = tensor1.matmul(tensor2)
                    encrypted_out = encrypted1.matmul(encrypted2)
                    private = isinstance(encrypted2, MPCTensor)
                    self._check(
                        encrypted_out,
                        reference,
                        "%s matmul broadcast failed"
                        % ("private" if private else "public"),
                    )

    def test_inplace(self):
        """Test inplace vs. out-of-place functions"""
        for op in ["add", "sub", "mul", "div"]:
            for tensor_type in [lambda x: x, MPCTensor]:
                tensor1 = get_random_test_tensor(is_float=True)
                tensor2 = get_random_test_tensor(is_float=True)

                reference = getattr(torch, op)(tensor1, tensor2)

                encrypted1 = MPCTensor(tensor1)
                encrypted2 = tensor_type(tensor2)

                input_tensor_id = id(encrypted1._tensor)
                input_encrypted_id = id(encrypted1)

                # Test that out-of-place functions do not modify the input
                private = isinstance(encrypted2, MPCTensor)
                encrypted_out = getattr(encrypted1, op)(encrypted2)
                self._check(
                    encrypted1,
                    tensor1,
                    "%s out-of-place %s modifies input"
                    % ("private" if private else "public", op),
                )
                self._check(
                    encrypted_out,
                    reference,
                    "%s out-of-place %s produces incorrect output"
                    % ("private" if private else "public", op),
                )
                self.assertFalse(id(encrypted_out._tensor) == input_tensor_id)
                self.assertFalse(id(encrypted_out) == input_encrypted_id)

                # Test that in-place functions modify the input
                encrypted_out = getattr(encrypted1, op + "_")(encrypted2)
                self._check(
                    encrypted1,
                    reference,
                    "%s in-place %s_ does not modify input"
                    % ("private" if private else "public", op),
                )
                self._check(
                    encrypted_out,
                    reference,
                    "%s in-place %s_ produces incorrect output"
                    % ("private" if private else "public", op),
                )
                self.assertTrue(id(encrypted_out._tensor) == input_tensor_id)
                self.assertTrue(id(encrypted_out) == input_encrypted_id)

    # TODO: Add following unit tests:
    def test_copy_clone(self):
        pass

    def test_index_select(self):
        pass

    def test_repeat_expand(self):
        pass

    def test_view_flatten(self):
        pass

    def test_roll(self):
        pass

    def test_fold_unfold(self):
        pass

    def test_to(self):
        pass

    def test_cumsum(self):
        pass

    def test_trace(self):
        pass

    def test_take(self):
        pass

    def test_flip(self):
        pass


# This code only runs when executing the file outside the test harness (e.g.
# via the buck target test_mpc_benchmark)
if __name__ == "__main__":
    TestMPC.benchmarks_enabled = True
    unittest.main()