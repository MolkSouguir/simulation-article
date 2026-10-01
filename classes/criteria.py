class Criteria:
    def __init__(self, name: str, score: float, weight: float, minimize: bool, attribute_name: str):
        self.name = name
        self.score = score
        self.weight = weight
        self.minimize = minimize
        self.attribute_name = attribute_name
        self.value = None
