"""BenchVCR public API."""

__version__ = "0.1.0"

from .cassette import Cassette, CassetteHeader, Exchange, validate_cassette
from .errors import (
    BenchVCRError,
    CassetteError,
    CassetteMismatchError,
    CassetteValidationError,
    CommunicationError,
    ConfigurationError,
    DisconnectError,
    ProtocolError,
    SessionStateError,
    TransportError,
    TransportTimeoutError,
    UnplayedInteractionsError,
)
from .faults import FaultPlan, load_fault_plan, probability_sample
from .session import RecordSession, ReplaySession, use_cassette
from .transport import TextTransport

__all__ = [
    "BenchVCRError",
    "Cassette",
    "CassetteError",
    "CassetteHeader",
    "CassetteMismatchError",
    "CassetteValidationError",
    "CommunicationError",
    "ConfigurationError",
    "DisconnectError",
    "Exchange",
    "FaultPlan",
    "ProtocolError",
    "RecordSession",
    "ReplaySession",
    "SessionStateError",
    "TextTransport",
    "TransportError",
    "TransportTimeoutError",
    "UnplayedInteractionsError",
    "load_fault_plan",
    "probability_sample",
    "use_cassette",
    "validate_cassette",
]
