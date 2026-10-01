"""
db/models/enums.py

Enums shared by the simulation, the database models and the API.
"""
import enum


class MachineTypeEnum(str, enum.Enum):
    VENTILATOR = "ventilator"
    DIALYSIS = "dialysis"


class MachineStatusEnum(str, enum.Enum):
    ACTIVE = "active"
    STANDBY = "standby"
    MAINTENANCE = "maintenance"


class SparePartTypeEnum(str, enum.Enum):
    SENSOR = "sensor"
    FILTER = "filter"
    BATTERY = "battery"
    GASKET = "gasket"
    VALVE = "valve"
    ROULEMENT = "roulement"
    KIT_CONSTRUCTOR = "kit constructor"


class SparePartStatusEnum(str, enum.Enum):
    USED = "used"
    NEW = "new"


class EventTypeEnum(str, enum.Enum):
    FAILURE = "failure"
    CORRECTIVE_MAINTENANCE = "corrective maintenance"
    PREVENTIVE_MAINTENANCE = "preventive maintenance"
    PURCHASE_REPLACEMENT = "purchase replacement"
    END_OF_MAINTENANCE = "end of maintenance"
    TO_SERVICE = "to service"
    OUT_OF_SERVICE = "out of service"
    START_OF_SIMULATION = "start of simulation"
    END_OF_SIMULATION = "end of simulation"


class DecisionMethodTypeEnum(str, enum.Enum):
    AHP = "AHP"
    TOPSIS = "TOPSIS"
    ELECTRE2 = "ELECTRE2"


class MaintenanceItemType(str, enum.Enum):
    """Tells machines and spare parts apart (used by MaintenanceItemAlternative)."""
    MACHINE = "machine"
    SPARE_PART = "spare part"
