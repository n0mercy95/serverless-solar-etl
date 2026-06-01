# Infrastructure — Estrategias Concretas de Limpieza (Patrón Strategy)

from app.infrastructure.strategies.hampel_filter_strategy import HampelFilterStrategy
from app.infrastructure.strategies.irradiance_consistency_strategy import (
    IrradianceConsistencyStrategy,
)
from app.infrastructure.strategies.irradiance_outlier_strategy import (
    IrradianceOutlierStrategy,
)
from app.infrastructure.strategies.missing_value_imputer_strategy import (
    MissingValueImputerStrategy,
)
from app.infrastructure.strategies.nighttime_zeroing_strategy import (
    NighttimeZeroingStrategy,
)
from app.infrastructure.strategies.thermodynamic_bounds_strategy import (
    ThermodynamicBoundsStrategy,
)

__all__ = [
    "HampelFilterStrategy",
    "IrradianceConsistencyStrategy",
    "IrradianceOutlierStrategy",
    "MissingValueImputerStrategy",
    "NighttimeZeroingStrategy",
    "ThermodynamicBoundsStrategy",
]
