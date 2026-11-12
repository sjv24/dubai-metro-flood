"""Load experiments/config.yaml once; every module reads parameters from CFG."""
from __future__ import annotations

import os

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "experiments", "config.yaml")

with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CFG: dict = yaml.safe_load(_fh)
