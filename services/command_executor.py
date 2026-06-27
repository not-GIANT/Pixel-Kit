import subprocess
import os
import threading
import time
import re
from pathlib import Path

from ..config import IS_WINDOWS, WIN_CREATION_FLAGS


class CommandExecutor:
    """Thread-safe command execution service for ADB/Fastboot operations.

    Handles subprocess lifecycle, busy-state management with locks,
    stdout parsing for progress feedback, and safe interactive shell
    operations that prevent pipe-buffer deadlocks.
    """

    def __init__(self, config, log=None):
        self.config = config
        self.log = log

        self._is_busy = False
        self._busy_lock = threading.Lock()
        self.current_process = None
        self.stop_event = threading.Event()
        self.cached_paths = {}

        # Callbacks for UI integration (set by the UI layer)
        self.on_console_output = None       # func(text, tag)
        self.on_footer_status = None        # func(text, color_hex)
        self.on_progress_set = None         # func(value)
        self.on_progress_indeterminate = None  # func()
        self.on_progress_stop = None         # func() — stops indeterminate animation
        self.on_command_finished = None     # func() — called after command completes
        self.on_busy_warning = None         # func()

    # --- Thread-safe busy flag ---

    def _set_busy(self, value):
        with self._busy_lock:
            old = self._is_busy
            self._is_busy = value
            return old

    @property
    def is_busy(self):
        with self._busy_lock:
            return self._is_busy

    # --- Tool discovery ---

    def check_tools(self):
        """Verify required tools exist and cache their paths."""
        self.cached_paths = {}
        if not self.config.platform_tools_dir.is_dir():
            raise FileNotFoundError(
                f"'{self.config.platform_tools_dir}' directory not found."
            )

        missing = []
        for tool in self.config.required_tools:
            tool_path = self.config.platform_tools_dir / tool
            if IS_WINDOWS:
                tool_exe = self.config.platform_tools_dir / f"{tool}.exe"
                if tool_exe.exists():
                    self.cached_paths[tool] = str(tool_exe.absolute())
                elif tool_path.exists():
                    self.cached_paths[tool] = str(tool_path.absolute())
                else:
                    missing.append(tool)
            else:
                if tool_path.exists():
                    self.cached_paths[tool] = str(tool_path.absolute())
                else:
                    missing.append(tool)
        return missing

    # --- Subprocess execution ---

    def execute_tool_command(self, tool, args_list, capture_output=True,
                             is_shell=False, combine_output=False):
        """Create a Popen for the given tool and arguments."""
        tool_path = self.cached_paths.get(tool)
        if not tool_path:
            tool_path = str((self.config.platform_tools_dir / tool).absolute())

        if is_shell:
            if IS_WINDOWS:
                args_str = " ".join(args_list) if isinstance(args_list, list) else args_list
                cmd = f'cmd.exe /K ""{tool_path}" {args_str}"'
                return subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE)
            else:
                cmd = [tool_path] + (args_list if isinstance(args_list, list) else args_list.split())
                return subprocess.Popen(['x-terminal-emulator', '-e'] + cmd)

        cmd = [tool_path] + (args_list if isinstance(args_list, list) else args_list.split())
        try:
            if capture_output:
                stderr_dest = subprocess.STDOUT if combine_output else subprocess.PIPE
                return subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=stderr_dest,
                    text=True, errors='replace', bufsize=1,
                    creationflags=WIN_CREATION_FLAGS
                )
            else:
                return subprocess.Popen(cmd, creationflags=WIN_CREATION_FLAGS)
        except Exception as e:
            self._console(f"Execution Error: {e}\n", "error")
            return None

    def communicate_with_timeout(self, process, timeout=5):
        if not process:
            return None, None
        try:
            return process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except Exception:
                pass
            return process.communicate()

    # --- Synchronous command execution ---

    def run_command(self, tool, args_list="", is_shell=False, task_name=None):
        """Run a command synchronously (blocks until complete).

        Manages the busy flag with save/restore semantics so nested
        calls from run_multiple_commands work correctly.
        """
        was_busy = self._set_busy(True)
        self.start_progress()
        self.stop_event.clear()

        name = task_name or "Command"
        self._footer(f"Running: {name}...", "#00bcd4")

        if task_name:
            self._console(f"--- Executing Command: {task_name} ---\n", "status")
        else:
            self._console("--- Executing Command ---\n", "status")

        try:
            process = self.execute_tool_command(tool, args_list, is_shell=is_shell, combine_output=True)
            self.current_process = process
            if process:
                if is_shell:
                    self._console(f"Interactive {tool} shell opened in a new window.\n")
                else:
                    for line in iter(process.stdout.readline, ''):
                        self._console(line, "command_output")
                        self._parse_flash_progress(line)

                    process.stdout.close()
                    return_code = process.wait()

                    if return_code != 0 and not self.stop_event.is_set():
                        self._console(f"Command failed with return code {return_code}\n", "error")
                        self._footer("Command Failed", "#f44336")
                    elif return_code == 0 and not self.stop_event.is_set():
                        self._footer("Finished Successfully", "#4caf50")
                        self._progress_set(1.0)
                    return return_code
            else:
                self._console("Failed to start process.\n", "error")
                self._footer("Process Start Failed", "#f44336")
                return -1
        except Exception as e:
            if not self.stop_event.is_set():
                self._console(f"An application error occurred: {e}\n", "error")
                self._footer(f"Error: {e}", "#f44336")
            return -1
        finally:
            self.current_process = None
            self._console("--- Command Finished ---\n\n", "status")
            self.stop_progress()
            if not was_busy:
                self._set_busy(False)

    def _parse_flash_progress(self, line):
        """Parse fastboot output lines for flashing progress feedback."""
        clean_line = line.strip()

        send_match = re.search(r"Sending\s+'([^']+)'\s+\((\d+)\s+KB\)", clean_line, re.IGNORECASE)
        write_match = re.search(r"Writing\s+'([^']+)'", clean_line, re.IGNORECASE)
        finished_match = re.search(r"Finished\.\s+Total\s+time:\s+([\d\.]+)s", clean_line, re.IGNORECASE)

        if send_match:
            part, size = send_match.group(1), send_match.group(2)
            self._footer(f"Flashing {part}... Sending ({size} KB)", "#2196f3")
            self._progress_set(0.3)
        elif write_match:
            part = write_match.group(1)
            self._footer(f"Flashing {part}... Writing partition", "#ff9800")
            self._progress_set(0.7)
        elif finished_match:
            t = finished_match.group(1)
            self._footer(f"Flashing finished successfully in {t}s!", "#4caf50")
            self._progress_set(1.0)

    # --- Threaded command execution ---

    def run_command_threaded(self, tool, args_list="", is_shell=False, task_name=None):
        """Run a command in a background thread. Returns True if started."""
        if self.is_busy:
            if self.on_busy_warning:
                self.on_busy_warning()
            return False
        thread = threading.Thread(
            target=self.run_command, args=(tool, args_list, is_shell, task_name)
        )
        thread.daemon = True
        thread.start()
        return True

    def run_multiple_commands(self, command_list, task_name=None):
        """Run multiple commands sequentially in a background thread."""
        if self.is_busy:
            if self.on_busy_warning:
                self.on_busy_warning()
            return False

        def run_all():
            self._set_busy(True)
            try:
                if task_name and self.log:
                    self.log.status(f"--- Executing Task: {task_name} ---\n")
                for cmd_parts in command_list:
                    if self.stop_event.is_set():
                        break
                    tool = cmd_parts[0]
                    args = cmd_parts[1:]
                    self.run_command(tool, args)
            finally:
                self._set_busy(False)

        thread = threading.Thread(target=run_all, daemon=True)
        thread.start()
        return True

    def stop_current_command(self):
        """Terminate the currently running process."""
        if self.current_process:
            self.stop_event.set()
            try:
                self.current_process.terminate()
                self._console("Command execution stopped by user.\n", "error")
            except Exception as e:
                self._console(f"Failed to terminate process: {e}\n", "error")
            self.stop_progress()

    # --- Interactive shell with deadlock prevention ---

    def run_interactive_shell(self, adb_path, commands, timeout=30):
        """Open a rooted ADB shell, send commands, drain stdout to prevent deadlock.

        Uses a separate reader thread to continuously drain stdout/stderr
        so the pipe buffer never fills up. This fixes the deadlock risk
        in the original CPID AT command implementation.

        Args:
            adb_path: Path to adb executable.
            commands: List of command strings to send after 'su'.
            timeout: Max seconds to wait for shell to exit.

        Returns:
            List of stdout output lines.
        """
        proc = subprocess.Popen(
            [adb_path, "shell"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            creationflags=WIN_CREATION_FLAGS
        )

        output_lines = []
        stop_reading = threading.Event()

        def read_stream(stream, storage):
            try:
                for line in iter(stream.readline, ''):
                    if stop_reading.is_set():
                        break
                    storage.append(line)
            except Exception:
                pass

        out_thread = threading.Thread(target=read_stream, args=(proc.stdout, output_lines), daemon=True)
        err_lines = []
        err_thread = threading.Thread(target=read_stream, args=(proc.stderr, err_lines), daemon=True)
        out_thread.start()
        err_thread.start()

        try:
            proc.stdin.write("su\n")
            proc.stdin.flush()
            time.sleep(1)

            for cmd in commands:
                proc.stdin.write(cmd + "\n")
                proc.stdin.flush()
                time.sleep(0.2)

            proc.stdin.write("exit\nexit\n")
            proc.stdin.flush()
            proc.stdin.close()

            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        finally:
            stop_reading.set()
            out_thread.join(timeout=5)
            err_thread.join(timeout=5)
            try:
                proc.stdout.close()
            except Exception:
                pass
            try:
                proc.stderr.close()
            except Exception:
                pass

        return output_lines

    # --- Internal callback helpers ---

    def _console(self, text, tag=None):
        if self.on_console_output:
            self.on_console_output(text, tag)

    def _footer(self, text, color):
        if self.on_footer_status:
            self.on_footer_status(text, color)

    def _progress_set(self, value):
        if self.on_progress_set:
            self.on_progress_set(value)

    def start_progress(self):
        if self.on_progress_indeterminate:
            self.on_progress_indeterminate()

    def stop_progress(self):
        if self.on_progress_stop:
            self.on_progress_stop()
        if self.on_progress_set:
            self.on_progress_set(0)
        if self.on_command_finished:
            self.on_command_finished()
