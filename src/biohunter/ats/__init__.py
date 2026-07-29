from .ashby import AshbyAdapter
from .base import ATSAdapter, RawPosting
from .greenhouse import GreenhouseAdapter
from .jobsyn import JobsynAdapter
from .jobvite import JobviteAdapter
from .lever import LeverAdapter
from .workday import WorkdayAdapter

REGISTRY: dict[str, ATSAdapter] = {
    "greenhouse": GreenhouseAdapter(),
    "lever": LeverAdapter(),
    "ashby": AshbyAdapter(),
    "workday": WorkdayAdapter(),
    "jobvite": JobviteAdapter(),
    "jobsyn": JobsynAdapter(),
}

__all__ = ["ATSAdapter", "RawPosting", "REGISTRY"]
