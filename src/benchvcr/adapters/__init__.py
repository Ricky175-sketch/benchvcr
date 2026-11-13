"""Optional third-party transport adapters.

Importing these wrappers does not import pyserial or PyVISA. Applications pass
already-created connection/resource objects and retain ownership until close.
"""

from .pyvisa import PyVISAAdapter
from .serial import SerialTextAdapter

__all__ = ["PyVISAAdapter", "SerialTextAdapter"]
