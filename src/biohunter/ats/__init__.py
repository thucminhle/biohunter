from .ashby import AshbyAdapter
from .base import ATSAdapter, RawPosting
from .greenhouse import GreenhouseAdapter
from .lever import LeverAdapter
from .workday import WorkdayAdapter

REGISTRY: dict[str, ATSAdapter] = {
    "greenhouse": GreenhouseAdapter(),
    "lever": LeverAdapter(),
    "ashby": AshbyAdapter(),
    "workday": WorkdayAdapter(),
}

__all__ = ["ATSAdapter", "RawPosting", "REGISTRY"]
