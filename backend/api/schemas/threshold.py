"""An instance's warning and critical thresholds, as the API shows and takes them."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from api.enums import ThresholdMetric

# Defaults would otherwise mark fields optional in the OpenAPI response schema.
_READ = ConfigDict(json_schema_serialization_defaults_required=True)

# A threshold value: a finite number, zero or more.
Threshold = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class ThresholdRead(BaseModel):
    model_config = _READ

    metric: ThresholdMetric
    # None means no line at that level.
    warning: float | None
    critical: float | None
    # Whether these are the metric's defaults rather than values someone set.
    is_default: bool


class InstanceThresholdsRead(BaseModel):
    model_config = _READ

    # One per metric, always all of them.
    thresholds: list[ThresholdRead]


class ThresholdWrite(BaseModel):
    warning: Threshold | None
    critical: Threshold | None
