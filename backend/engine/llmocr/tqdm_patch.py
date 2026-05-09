"""Silence Surya's internal tqdm progress bars that pollute log output."""

import os

os.environ.setdefault("SURYA_DISABLE_TQDM", "1")
