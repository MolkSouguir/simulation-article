from enum import Enum

class EventType(str, Enum):
    FAILURE = "failure",
    CORRECTIVE_MAINTENANCE = "corrective maintenance",
    PREVENTIVE_MAINTENANCE = "preventive maintenance",
    PURCHASE_REPLACEMENT = "purchase replacement",
    END_OF_MAINTENANCE = "end of maintenance",
    TO_SERVICE = "to service",
    OUT_OF_SERVICE = "out of service",
    START_OF_SIMULATION = "start of simulation"
    END_OF_SIMULATION = "end of simulation"