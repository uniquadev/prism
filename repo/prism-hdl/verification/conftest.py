"""Shared deterministic verification configuration."""

from __future__ import annotations

import random

DETERMINISTIC_SEED = 0x50524953
random.seed(DETERMINISTIC_SEED)
