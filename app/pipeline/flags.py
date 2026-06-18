"""Feature flags for the accuracy pipeline.

Everything defaults to OFF. With the default ``PipelineConfig`` the engine runs
the plain Config F generation path, so the documented baseline is unchanged.
Flags can be set per-process via environment variables (read by
``PipelineConfig.from_env``) or per-request (the API accepts overrides).

Environment variables:
    DBNAV_SELF_CORRECTION          bool   enable the self-correction loop
    DBNAV_SELF_CORRECTION_ITERS    int    max repair iterations (default 2)
    DBNAV_SELF_CORRECTION_RETRY_EMPTY bool treat an empty result set as a fault
    DBNAV_SELF_CORRECTION_TEMPERATURE float repair sampling temperature (default 0.0)
    DBNAV_VOTING                   bool   enable self-consistency voting
    DBNAV_VOTING_N                 int    candidate count for voting (default 5)
    DBNAV_VOTING_TEMPERATURE       float  candidate sampling temperature (default 0.7)
    DBNAV_JOIN_PATHS               bool   enable FK join-path validation and repair
    DBNAV_VALUE_CHECK              bool   enable value-domain validation and repair
    DBNAV_CODE_GLOSSARY            bool   inject the code dictionary before generation
"""
import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except (TypeError, ValueError):
        return default


@dataclass
class PipelineConfig:
    """Toggles for inference-time accuracy techniques.

    The default instance is the Config F baseline: no correction, no voting.
    """

    self_correction: bool = False
    correction_max_iters: int = 2
    correction_retry_on_empty: bool = False
    correction_temperature: float = 0.0

    voting: bool = False
    voting_n: int = 5
    voting_temperature: float = 0.7

    join_paths: bool = False

    value_check: bool = False

    code_glossary: bool = False

    @classmethod
    def from_env(cls) -> "PipelineConfig":
        return cls(
            self_correction=_env_bool("DBNAV_SELF_CORRECTION", False),
            correction_max_iters=_env_int("DBNAV_SELF_CORRECTION_ITERS", 2),
            correction_retry_on_empty=_env_bool("DBNAV_SELF_CORRECTION_RETRY_EMPTY", False),
            correction_temperature=_env_float("DBNAV_SELF_CORRECTION_TEMPERATURE", 0.0),
            voting=_env_bool("DBNAV_VOTING", False),
            voting_n=_env_int("DBNAV_VOTING_N", 5),
            voting_temperature=_env_float("DBNAV_VOTING_TEMPERATURE", 0.7),
            join_paths=_env_bool("DBNAV_JOIN_PATHS", False),
            value_check=_env_bool("DBNAV_VALUE_CHECK", False),
            code_glossary=_env_bool("DBNAV_CODE_GLOSSARY", False),
        )

    def merged_with(self, **overrides) -> "PipelineConfig":
        """Return a copy with the given non-None overrides applied.

        Used by the API to apply per-request flags on top of the server default.
        Keys whose value is None are ignored so callers can pass through optional
        request fields directly.
        """
        data = {
            "self_correction": self.self_correction,
            "correction_max_iters": self.correction_max_iters,
            "correction_retry_on_empty": self.correction_retry_on_empty,
            "correction_temperature": self.correction_temperature,
            "voting": self.voting,
            "voting_n": self.voting_n,
            "voting_temperature": self.voting_temperature,
            "join_paths": self.join_paths,
            "value_check": self.value_check,
            "code_glossary": self.code_glossary,
        }
        for key, value in overrides.items():
            if value is not None and key in data:
                data[key] = value
        return PipelineConfig(**data)