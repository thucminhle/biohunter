from .ashby import AshbyAdapter
from .base import ATSAdapter, RawPosting
from .greenhouse import GreenhouseAdapter
from .lever import LeverAdapter

REGISTRY: dict[str, ATSAdapter] = {
    "greenhouse": GreenhouseAdapter(),
    "lever": LeverAdapter(),
    "ashby": AshbyAdapter(),
}

__all__ = ["ATSAdapter", "RawPosting", "REGISTRY"]
