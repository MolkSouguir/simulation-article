# State shared by the whole backend. It lives in module-level variables, so the
# API can only serve one user at a time.
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from db.models import MachineModel

db_machines: list["MachineModel"] = []    # the fleet, filled by db/loader.py
inflation_rate: float = 0.02              # yearly, applied to machine prices only
simulations: dict[str, list] = {}         # "simulation-<n>" -> events of that run (the last alternative's)
base_year: int = date.today().year        # calendar year of t = 0
