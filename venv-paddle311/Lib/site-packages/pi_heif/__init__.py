"""Provide all possible stuff that can be used."""


# start delvewheel patch
def _delvewheel_patch_1_12_0():
    import os
    if os.path.isdir(libs_dir := os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, '.'))):
        os.add_dll_directory(libs_dir)


_delvewheel_patch_1_12_0()
del _delvewheel_patch_1_12_0
# end delvewheel patch

from . import options
from ._lib_info import libheif_info, libheif_version
from ._version import __version__
from .as_plugin import (
    HeifImageFile,
    register_heif_opener,
)
from .constants import (
    HeifColorPrimaries,
    HeifDepthRepresentationType,
    HeifMatrixCoefficients,
    HeifTransferCharacteristics,
)
from .heif import (
    HeifAuxImage,
    HeifDepthImage,
    HeifFile,
    HeifImage,
    encode,
    from_bytes,
    from_pillow,
    is_supported,
    open_heif,
    read_heif,
)
from .misc import get_file_mimetype, load_libheif_plugin, set_orientation
