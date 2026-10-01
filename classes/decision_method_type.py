from enum import Enum


class DecisionMethodType(str, Enum):
    AHP = "AHP"
    TOPSIS = "TOPSIS"
    ELECTRE2 = "ELECTRE2"