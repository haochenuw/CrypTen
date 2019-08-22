#!/usr/bin/env python3

# dependencies:
import logging
import unittest
from test.multiprocess_test_case import MultiProcessTestCase, get_random_test_tensor


BinarySharedTensor, is_int_tensor = None, None


def import_crypten():
    """
    Imports CrypTen types. This function is called after environment variables
    in MultiProcessTestCase.setUp() are set, and sets the class references for
    all test functions.
    """
    global BinarySharedTensor
    global is_int_tensor
    from crypten.primitives.binary.binary import (
        BinarySharedTensor as _BinarySharedTensor,
    )
    from crypten.common.tensor_types import is_int_tensor as _is_int_tensor

    BinarySharedTensor = _BinarySharedTensor
    is_int_tensor = _is_int_tensor


class TestBinary(MultiProcessTestCase):
    """
        This class tests all functions of BinarySharedTensor.
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

        self.assertTrue(is_int_tensor(reference), "reference must be a long")
        test_passed = (tensor == reference).all().item() == 1
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
            reference = get_random_test_tensor(size=size, is_float=False)
            with self.benchmark(tensor_type="BinarySharedTensor") as bench:
                for _ in bench.iters:
                    encrypted_tensor = BinarySharedTensor(reference)
                    self._check(encrypted_tensor, reference, "en/decryption failed")

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
            tensor = get_random_test_tensor(size=size, is_float=False)
            encrypted_tensor = BinarySharedTensor(tensor)

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

    def test_XOR(self):
        """Test bitwise-XOR function on BinarySharedTensor"""
        for tensor_type in [lambda x: x, BinarySharedTensor]:
            tensor = get_random_test_tensor(is_float=False)
            tensor2 = get_random_test_tensor(is_float=False)
            reference = tensor ^ tensor2
            encrypted_tensor = BinarySharedTensor(tensor)
            encrypted_tensor2 = tensor_type(tensor2)
            with self.benchmark(tensor_type=tensor_type.__name__) as bench:
                for _ in bench.iters:
                    encrypted_out = encrypted_tensor ^ encrypted_tensor2
            self._check(encrypted_out, reference, "%s XOR failed" % tensor_type)

    def test_AND(self):
        """Test bitwise-AND function on BinarySharedTensor"""
        for tensor_type in [lambda x: x, BinarySharedTensor]:
            tensor = get_random_test_tensor(is_float=False)
            tensor2 = get_random_test_tensor(is_float=False)
            reference = tensor & tensor2
            encrypted_tensor = BinarySharedTensor(tensor)
            encrypted_tensor2 = tensor_type(tensor2)
            with self.benchmark(tensor_type=tensor_type.__name__) as bench:
                for _ in bench.iters:
                    encrypted_out = encrypted_tensor & encrypted_tensor2
            self._check(encrypted_out, reference, "%s AND failed" % tensor_type)

    def test_OR(self):
        """Test bitwise-OR function on BinarySharedTensor"""
        for tensor_type in [lambda x: x, BinarySharedTensor]:
            tensor = get_random_test_tensor(is_float=False)
            tensor2 = get_random_test_tensor(is_float=False)
            reference = tensor | tensor2
            encrypted_tensor = BinarySharedTensor(tensor)
            encrypted_tensor2 = tensor_type(tensor2)
            with self.benchmark(tensor_type=tensor_type.__name__) as bench:
                for _ in bench.iters:
                    encrypted_out = encrypted_tensor | encrypted_tensor2
            self._check(encrypted_out, reference, "%s OR failed" % tensor_type)

    def test_invert(self):
        """Test bitwise-invert function on BinarySharedTensor"""
        tensor = get_random_test_tensor(is_float=False)
        encrypted_tensor = BinarySharedTensor(tensor)
        reference = ~tensor
        with self.benchmark() as bench:
            for _ in bench.iters:
                encrypted_out = ~encrypted_tensor
        self._check(encrypted_out, reference, "invert failed")

    def test_add(self):
        """Tests add using binary shares"""
        for tensor_type in [lambda x: x, BinarySharedTensor]:
            tensor = get_random_test_tensor(is_float=False)
            tensor2 = get_random_test_tensor(is_float=False)
            reference = tensor + tensor2
            encrypted_tensor = BinarySharedTensor(tensor)
            encrypted_tensor2 = tensor_type(tensor2)
            with self.benchmark(tensor_type=tensor_type.__name__) as bench:
                for _ in bench.iters:
                    encrypted_out = encrypted_tensor + encrypted_tensor2
            self._check(encrypted_out, reference, "%s AND failed" % tensor_type)

    def test_sum(self):
        """Tests sum using binary shares"""
        tensor = get_random_test_tensor(size=(5, 5, 5), is_float=False)
        encrypted = BinarySharedTensor(tensor)
        self._check(encrypted.sum(), tensor.sum(), "sum failed")

        for dim in [0, 1, 2]:
            reference = tensor.sum(dim)
            with self.benchmark(type="sum", dim=dim) as bench:
                for _ in bench.iters:
                    encrypted_out = encrypted.sum(dim)
            self._check(encrypted_out, reference, "sum failed")

    def test_get_set(self):
        for tensor_type in [lambda x: x, BinarySharedTensor]:
            for size in range(1, 5):
                # Test __getitem__
                tensor = get_random_test_tensor(size=(size, size), is_float=False)
                reference = tensor[:, 0]

                encrypted_tensor = BinarySharedTensor(tensor)
                encrypted_out = encrypted_tensor[:, 0]
                self._check(encrypted_out, reference, "getitem failed")

                reference = tensor[0, :]
                encrypted_out = encrypted_tensor[0, :]
                self._check(encrypted_out, reference, "getitem failed")

                # Test __setitem__
                tensor2 = get_random_test_tensor(size=(size,), is_float=False)
                reference = tensor.clone()
                reference[:, 0] = tensor2

                encrypted_out = BinarySharedTensor(tensor)
                encrypted2 = tensor_type(tensor2)
                encrypted_out[:, 0] = encrypted2

                self._check(
                    encrypted_out, reference, "%s setitem failed" % type(encrypted2)
                )

                reference = tensor.clone()
                reference[0, :] = tensor2

                encrypted_out = BinarySharedTensor(tensor)
                encrypted2 = tensor_type(tensor2)
                encrypted_out[0, :] = encrypted2

                self._check(
                    encrypted_out, reference, "%s setitem failed" % type(encrypted2)
                )

    def test_inplace(self):
        """Test inplace vs. out-of-place functions"""
        for op in ["__xor__", "__and__", "__or__"]:
            for tensor_type in [lambda x: x, BinarySharedTensor]:
                tensor1 = get_random_test_tensor(is_float=False)
                tensor2 = get_random_test_tensor(is_float=False)

                reference = getattr(tensor1, op)(tensor2)

                encrypted1 = BinarySharedTensor(tensor1)
                encrypted2 = tensor_type(tensor2)

                input_plain_id = id(encrypted1._tensor)
                input_encrypted_id = id(encrypted1)

                # Test that out-of-place functions do not modify the input
                private = isinstance(encrypted2, BinarySharedTensor)
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
                self.assertFalse(id(encrypted_out._tensor) == input_plain_id)
                self.assertFalse(id(encrypted_out) == input_encrypted_id)

                # Test that in-place functions modify the input
                inplace_op = op[:2] + "i" + op[2:]
                encrypted_out = getattr(encrypted1, inplace_op)(encrypted2)
                self._check(
                    encrypted1,
                    reference,
                    "%s in-place %s does not modify input"
                    % ("private" if private else "public", inplace_op),
                )
                self._check(
                    encrypted_out,
                    reference,
                    "%s in-place %s produces incorrect output"
                    % ("private" if private else "public", inplace_op),
                )
                self.assertTrue(id(encrypted_out._tensor) == input_plain_id)
                self.assertTrue(id(encrypted_out) == input_encrypted_id)


# This code only runs when executing the file outside the test harness (e.g.
# via the buck target test_spdz_benchmark)
if __name__ == "__main__":
    TestBinary.benchmarks_enabled = True
    unittest.main()