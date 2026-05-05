
import paddle
from paddle import _C_ops
from .. import core

def _all(*args, **kwargs):
    return _C_ops.all(*args, **kwargs)

def _any(*args, **kwargs):
    return _C_ops.any(*args, **kwargs)

def _bmm(*args, **kwargs):
    return _C_ops.bmm(*args, **kwargs)

def _cos(*args, **kwargs):
    return _C_ops.cos(*args, **kwargs)

def _floor(*args, **kwargs):
    return _C_ops.floor(*args, **kwargs)

def _isfinite(*args, **kwargs):
    return _C_ops.isfinite(*args, **kwargs)

def _isinf(*args, **kwargs):
    return _C_ops.isinf(*args, **kwargs)

def _isnan(*args, **kwargs):
    return _C_ops.isnan(*args, **kwargs)

def _log(*args, **kwargs):
    return _C_ops.log(*args, **kwargs)

def _logsumexp(*args, **kwargs):
    return _C_ops.logsumexp(*args, **kwargs)

def _roll(*args, **kwargs):
    return _C_ops.roll(*args, **kwargs)

def _rsqrt(*args, **kwargs):
    return _C_ops.rsqrt(*args, **kwargs)

def _sigmoid(*args, **kwargs):
    return _C_ops.sigmoid(*args, **kwargs)

def _sign(*args, **kwargs):
    return _C_ops.sign(*args, **kwargs)

def _sin(*args, **kwargs):
    return _C_ops.sin(*args, **kwargs)

def _sqrt(*args, **kwargs):
    return _C_ops.sqrt(*args, **kwargs)

def _tril(*args, **kwargs):
    return _C_ops.tril(*args, **kwargs)

def _triu(*args, **kwargs):
    return _C_ops.triu(*args, **kwargs)

def _amin(*args, **kwargs):
    return _C_ops.amin(*args, **kwargs)

def _amax(*args, **kwargs):
    return _C_ops.amax(*args, **kwargs)

def _matmul(*args, **kwargs):
    return _C_ops.matmul(*args, **kwargs)

def _multiply(*args, **kwargs):
    return _C_ops.multiply(*args, **kwargs)

def _maximum(*args, **kwargs):
    return _C_ops.maximum(*args, **kwargs)

def _minimum(*args, **kwargs):
    return _C_ops.minimum(*args, **kwargs)

def _greater_than(*args, **kwargs):
    return _C_ops.greater_than(*args, **kwargs)

def _expand_as(*args, **kwargs):
    return _C_ops.expand_as(*args, **kwargs)

def _logical_and(*args, **kwargs):
    return _C_ops.logical_and(*args, **kwargs)

def _logical_or(*args, **kwargs):
    return _C_ops.logical_or(*args, **kwargs)

def _logical_xor(*args, **kwargs):
    return _C_ops.logical_xor(*args, **kwargs)

def _logical_not(*args, **kwargs):
    return _C_ops.logical_not(*args, **kwargs)

methods_map = [
  ('all',_all),
   ('any',_any),
   ('bmm',_bmm),
   ('cos',_cos),
   ('floor',_floor),
   ('isfinite',_isfinite),
   ('isinf',_isinf),
   ('isnan',_isnan),
   ('log',_log),
   ('logsumexp',_logsumexp),
   ('roll',_roll),
   ('rsqrt',_rsqrt),
   ('sigmoid',_sigmoid),
   ('sign',_sign),
   ('sin',_sin),
   ('sqrt',_sqrt),
   ('tril',_tril),
   ('triu',_triu),
   ('amin',_amin),
   ('amax',_amax),
   ('matmul',_matmul),
   ('multiply',_multiply),
   ('maximum',_maximum),
   ('minimum',_minimum),
   ('greater_than',_greater_than),
   ('expand_as',_expand_as),
   ('logical_and',_logical_and),
   ('logical_or',_logical_or),
   ('logical_xor',_logical_xor),
   ('logical_not',_logical_not)
]


funcs_map = [
  ('all',_all),
   ('any',_any),
   ('bmm',_bmm),
   ('cos',_cos),
   ('floor',_floor),
   ('isfinite',_isfinite),
   ('isinf',_isinf),
   ('isnan',_isnan),
   ('log',_log),
   ('logsumexp',_logsumexp),
   ('roll',_roll),
   ('rsqrt',_rsqrt),
   ('sigmoid',_sigmoid),
   ('sign',_sign),
   ('sin',_sin),
   ('sqrt',_sqrt),
   ('tril',_tril),
   ('triu',_triu),
   ('amin',_amin),
   ('amax',_amax),
   ('matmul',_matmul),
   ('multiply',_multiply),
   ('maximum',_maximum),
   ('minimum',_minimum),
   ('greater_than',_greater_than),
   ('expand_as',_expand_as),
   ('logical_and',_logical_and),
   ('logical_or',_logical_or),
   ('logical_xor',_logical_xor),
   ('logical_not',_logical_not)
]


nn_funcs_map = [
  ('sigmoid',_sigmoid)
]


def monkey_patch_generated_methods_for_tensor():

    # set methods for paddle.Tensor in dygraph
    local_tensor = core.eager.Tensor
    for method_name, method in methods_map:
        setattr(local_tensor, method_name, method)
        setattr(paddle.tensor, method_name, method)


    # set functions for paddle
    for method_name, method in funcs_map:
        setattr(paddle, method_name, method)


    # set functions for paddle.nn.functional
    for method_name, method in nn_funcs_map:
        setattr(paddle.nn.functional, method_name, method)
