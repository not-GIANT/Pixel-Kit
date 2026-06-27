"""QtBridge — the only glue between the framework-agnostic services layer and Qt.

The services layer (pixelkit/services/*) is intentionally pure Python with zero
UI framework coupling. It communicates upward via plain callbacks set on the
CommandExecutor:

    executor.on_console_output    = func(text, tag)
    executor.on_footer_status     = func(text, color_hex)
    executor.on_progress_set      = func(value)
    executor.on_progress_indeterminate = func()
    executor.on_progress_stop     = func()
    executor.on_command_finished  = func()
    executor.on_busy_warning      = func()

The old CTk GUI marshaled each through `self.after(0, ...)` to hop back to the
Tk main thread. Qt signals are already thread-safe (queued connections across
threads), so this bridge re-emits each callback as a Qt signal — eliminating
all manual marshaling. Services code is unchanged.

Tag mapping: the services use CTk-style text tags ("status"/"error"/
"command_output"/"info"); LogView expects M3 log levels
("info"/"success"/"warn"/"error"). The bridge normalizes here so neither side
needs to know about the other.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

# CTk service tag → M3 log-view level
_TAG_TO_LEVEL = {
    "status": "info",
    "command_output": "success",
    "error": "error",
    "info": "info",
}


class QtBridge(QObject):
    """Re-emits CommandExecutor callbacks as thread-safe Qt signals."""

    # --- Signals (all cross-thread safe via Qt's queued-connection mechanism) ---
    console_output = Signal(str, str)   # (text, level)
    footer_status = Signal(str, str)    # (text, color_hex)
    progress_set = Signal(float)
    progress_pulse = Signal()           # indeterminate animation start
    progress_stop = Signal()
    command_done = Signal()
    busy_warning = Signal()
    device_status = Signal(object)      # DeviceInfo or None

    def bind_executor(self, executor) -> None:
        """Wire CommandExecutor callbacks to Qt signals."""
        executor.on_console_output = self._emit_console
        executor.on_footer_status = self.footer_status.emit
        executor.on_progress_set = self.progress_set.emit
        executor.on_progress_indeterminate = self.progress_pulse.emit
        executor.on_progress_stop = self.progress_stop.emit
        executor.on_command_finished = self.command_done.emit
        executor.on_busy_warning = self.busy_warning.emit

    def bind_device_monitor(self, device_monitor) -> None:
        """Wire DeviceMonitor's status-change callback to a Qt signal."""
        device_monitor.on_status_change = lambda device_info: \
            self.device_status.emit(device_info)

    # --- internals ---

    def _emit_console(self, text: str, tag: str) -> None:
        """Normalize the service's CTk-style tag into an M3 log level."""
        level = _TAG_TO_LEVEL.get(tag, "info")
        self.console_output.emit(text, level)
