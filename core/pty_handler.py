"""
core/pty_handler.py
===================
Professional PTY (Pseudo Terminal) handler that manages the actual terminal process.
Handles fork/exec, PTY creation, I/O multiplexing, and process management.
Fully compatible with Linux/macOS.
"""

import os
import sys
import pty
import fcntl
import struct
import termios
import signal
import select
import threading
import subprocess
import errno
from typing import Optional, Callable
from PyQt6.QtCore import QObject, pyqtSignal, QThread, QTimer


class PTYWorker(QThread):
    """
    Background thread that reads from the PTY master fd and emits data.
    Runs in a tight loop using select() for efficient I/O.
    """

    # Signals
    data_received = pyqtSignal(bytes)          # Raw bytes from terminal
    process_exited = pyqtSignal(int)           # Exit code
    error_occurred = pyqtSignal(str)           # Error message

    # Buffer size for reading PTY output
    READ_BUFFER_SIZE = 65536  # 64KB chunks

    def __init__(self, master_fd: int, pid: int, parent=None):
        super().__init__(parent)
        self.master_fd = master_fd
        self.pid = pid
        self._running = True
        self._lock = threading.Lock()

    def run(self):
        """Main read loop - runs in background thread."""
        while self._running:
            try:
                # Use select() with timeout to allow clean shutdown
                r, _, _ = select.select([self.master_fd], [], [], 0.05)

                if r:
                    try:
                        data = os.read(self.master_fd, self.READ_BUFFER_SIZE)
                        if data:
                            self.data_received.emit(data)
                        else:
                            # EOF - process died
                            break
                    except OSError as e:
                        if e.errno in (errno.EIO, errno.EBADF):
                            # EIO: process died, EBADF: fd closed
                            break
                        elif e.errno == errno.EINTR:
                            # Interrupted by signal, continue
                            continue
                        else:
                            self.error_occurred.emit(f"PTY read error: {e}")
                            break

            except (ValueError, OSError):
                # select() failed, fd likely closed
                break
            except Exception as e:
                self.error_occurred.emit(f"PTY worker error: {e}")
                break

        # Check exit status
        try:
            _, status = os.waitpid(self.pid, os.WNOHANG)
            exit_code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else -1
            self.process_exited.emit(exit_code)
        except ChildProcessError:
            self.process_exited.emit(0)
        except Exception:
            self.process_exited.emit(-1)

    def stop(self):
        """Signal the worker to stop."""
        self._running = False


class PTYHandler(QObject):
    """
    Manages a PTY-backed terminal session.
    
    Creates a real pseudo-terminal with a shell process, handles:
    - PTY creation and sizing (TIOCSWINSZ)
    - Shell process spawning  
    - Bidirectional I/O
    - Signal handling (SIGWINCH, SIGTERM)
    - Process lifecycle management
    
    Architecture mirrors VS Code's node-pty implementation.
    """

    # ─────────────────────────────────────────────
    # Signals
    # ─────────────────────────────────────────────
    data_received    = pyqtSignal(bytes)   # Data from shell to display
    process_started  = pyqtSignal(int)     # PID of shell process
    process_exited   = pyqtSignal(int)     # Exit code
    error_occurred   = pyqtSignal(str)     # Error string
    title_changed    = pyqtSignal(str)     # OSC title change

    # ─────────────────────────────────────────────
    # Constants
    # ─────────────────────────────────────────────
    DEFAULT_COLS = 220
    DEFAULT_ROWS = 50
    WRITE_CHUNK_SIZE = 4096

    def __init__(self, parent=None):
        super().__init__(parent)

        # PTY state
        self.master_fd: Optional[int] = None
        self.slave_fd:  Optional[int] = None
        self.child_pid: Optional[int] = None

        # Dimensions
        self.cols = self.DEFAULT_COLS
        self.rows = self.DEFAULT_ROWS

        # Shell configuration
        self.shell = self._detect_shell()
        self.env   = self._build_env()

        # Worker thread
        self._worker: Optional[PTYWorker] = None

        # State
        self._running = False
        self._write_lock = threading.Lock()

    # ─────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────

    def start(self, cols: int = None, rows: int = None,
              shell: str = None, cwd: str = None) -> bool:
        """
        Spawn the shell inside a new PTY.
        Returns True on success, False on failure.
        """
        if self._running:
            return True

        if cols: self.cols = cols
        if rows: self.rows = rows
        if shell: self.shell = shell

        cwd = cwd or os.path.expanduser("~")

        try:
            self._create_pty(cwd)
            self._start_worker()
            self._running = True
            self.process_started.emit(self.child_pid)
            return True

        except Exception as e:
            self.error_occurred.emit(f"Failed to start PTY: {e}")
            self._cleanup()
            return False

    def write(self, data: bytes) -> bool:
        """
        Write bytes to the PTY master (stdin of shell).
        Thread-safe. Returns True on success.
        """
        if not self._running or self.master_fd is None:
            return False

        with self._write_lock:
            try:
                # Write in chunks to handle large pastes
                offset = 0
                while offset < len(data):
                    chunk = data[offset:offset + self.WRITE_CHUNK_SIZE]
                    written = os.write(self.master_fd, chunk)
                    offset += written
                return True
            except OSError as e:
                if e.errno != errno.EIO:
                    self.error_occurred.emit(f"PTY write error: {e}")
                return False

    def write_text(self, text: str) -> bool:
        """Write a string (UTF-8 encoded) to the PTY."""
        return self.write(text.encode("utf-8", errors="replace"))

    def resize(self, cols: int, rows: int):
        """
        Resize the PTY window (TIOCSWINSZ).
        This notifies the shell of the new terminal dimensions.
        """
        if not self._running or self.master_fd is None:
            return

        self.cols = max(1, cols)
        self.rows = max(1, rows)

        try:
            # struct winsize { unsigned short ws_row, ws_col, ws_xpixel, ws_ypixel; }
            winsize = struct.pack("HHHH", self.rows, self.cols, 0, 0)
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)

            # Send SIGWINCH to notify the process group
            if self.child_pid:
                try:
                    os.killpg(os.getpgid(self.child_pid), signal.SIGWINCH)
                except (ProcessLookupError, PermissionError):
                    pass

        except Exception as e:
            # Non-fatal - just log
            pass

    def stop(self):
        """Terminate the shell and clean up."""
        if not self._running:
            return

        self._running = False

        # Stop reader thread first
        if self._worker:
            self._worker.stop()
            self._worker.quit()
            self._worker.wait(2000)  # Wait up to 2s

        # Send SIGTERM then SIGKILL
        if self.child_pid:
            try:
                os.killpg(os.getpgid(self.child_pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                pass

            # Wait briefly for graceful exit
            import time
            time.sleep(0.1)

            try:
                os.killpg(os.getpgid(self.child_pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass

        self._cleanup()

    def is_running(self) -> bool:
        """Check if the shell process is alive."""
        if not self._running or not self.child_pid:
            return False
        try:
            os.kill(self.child_pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False

    def get_pid(self) -> Optional[int]:
        """Return the PID of the shell process."""
        return self.child_pid

    def send_signal(self, sig: signal.Signals):
        """Send a signal to the shell process group."""
        if self.child_pid:
            try:
                os.killpg(os.getpgid(self.child_pid), sig)
            except (ProcessLookupError, OSError):
                pass

    def send_interrupt(self):
        """Send Ctrl+C (SIGINT) to the current process."""
        self.send_signal(signal.SIGINT)

    def send_eof(self):
        """Send Ctrl+D (EOF)."""
        self.write(b"\x04")

    def send_suspend(self):
        """Send Ctrl+Z (SIGTSTP)."""
        self.send_signal(signal.SIGTSTP)

    # ─────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────

    def _create_pty(self, cwd: str):
        """Create PTY pair and fork shell process."""

        # Open a new PTY pair
        self.master_fd, self.slave_fd = pty.openpty()

        # Set initial terminal size
        winsize = struct.pack("HHHH", self.rows, self.cols, 0, 0)
        fcntl.ioctl(self.slave_fd, termios.TIOCSWINSZ, winsize)

        # Set raw termios on slave
        self._configure_termios(self.slave_fd)

        # Set master to non-blocking
        flags = fcntl.fcntl(self.master_fd, fcntl.F_GETFL)
        fcntl.fcntl(self.master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        # Fork!
        self.child_pid = os.fork()

        if self.child_pid == 0:
            # ─── Child process ───
            try:
                # Create new session - become session leader
                os.setsid()

                # Set slave as controlling terminal
                fcntl.ioctl(self.slave_fd, termios.TIOCSCTTY, 0)

                # Redirect stdio to slave PTY
                os.dup2(self.slave_fd, 0)  # stdin
                os.dup2(self.slave_fd, 1)  # stdout
                os.dup2(self.slave_fd, 2)  # stderr

                # Close extra fds
                os.close(self.slave_fd)
                os.close(self.master_fd)

                # Close all other fds
                try:
                    max_fd = os.sysconf("SC_OPEN_MAX")
                except (ValueError, AttributeError):
                    max_fd = 256
                for fd in range(3, max_fd):
                    try:
                        os.close(fd)
                    except OSError:
                        pass

                # Change directory
                try:
                    os.chdir(cwd)
                except OSError:
                    os.chdir(os.path.expanduser("~"))

                # Set environment
                os.environ.update(self.env)

                # Exec shell
                shell_name = os.path.basename(self.shell)
                os.execvpe(
                    self.shell,
                    [f"-{shell_name}"],   # Login shell prefix
                    os.environ
                )
            except Exception as e:
                os.write(2, f"PTY child error: {e}\n".encode())
                os._exit(1)

        else:
            # ─── Parent process ───
            # Close slave fd in parent (shell owns it)
            os.close(self.slave_fd)
            self.slave_fd = None

    def _configure_termios(self, fd: int):
        """Configure terminal attributes for the slave PTY."""
        try:
            attrs = termios.tcgetattr(fd)

            # Input flags
            attrs[0] |= termios.ICRNL   # CR -> NL
            attrs[0] |= termios.IXON    # XON/XOFF flow control
            attrs[0] &= ~termios.IGNBRK
            attrs[0] &= ~termios.BRKINT

            # Output flags
            attrs[1] |= termios.OPOST   # Post-process output
            attrs[1] |= termios.ONLCR   # NL -> CR+NL

            # Control flags
            attrs[2] |= termios.CS8     # 8-bit chars

            # Local flags
            attrs[3] |= termios.ECHO    # Echo input chars
            attrs[3] |= termios.ECHOE   # Echo erase
            attrs[3] |= termios.ECHOK   # Echo kill
            attrs[3] |= termios.ICANON  # Canonical mode
            attrs[3] |= termios.ISIG    # Enable signals
            attrs[3] |= termios.IEXTEN  # Extended processing

            # Special chars
            attrs[6][termios.VMIN]  = 1
            attrs[6][termios.VTIME] = 0

            termios.tcsetattr(fd, termios.TCSANOW, attrs)
        except Exception:
            pass  # Non-critical

    def _start_worker(self):
        """Start the background reader thread."""
        self._worker = PTYWorker(self.master_fd, self.child_pid)
        self._worker.data_received.connect(self.data_received)
        self._worker.process_exited.connect(self._on_process_exited)
        self._worker.error_occurred.connect(self.error_occurred)
        self._worker.start()

    def _on_process_exited(self, exit_code: int):
        """Handle shell process exit."""
        self._running = False
        self.process_exited.emit(exit_code)

    def _cleanup(self):
        """Close all file descriptors."""
        for fd in [self.master_fd, self.slave_fd]:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass

        self.master_fd = None
        self.slave_fd  = None
        self.child_pid = None

    def _detect_shell(self) -> str:
        """Detect the best available shell."""
        # Check user's default shell
        user_shell = os.environ.get("SHELL", "")
        if user_shell and os.path.isfile(user_shell) and os.access(user_shell, os.X_OK):
            return user_shell

        # Fallback order
        for shell in ["/bin/bash", "/usr/bin/bash", "/bin/zsh",
                      "/usr/bin/zsh", "/bin/sh"]:
            if os.path.isfile(shell) and os.access(shell, os.X_OK):
                return shell

        return "/bin/sh"

    def _build_env(self) -> dict:
        """Build the environment for the shell process."""
        env = os.environ.copy()

        # Terminal identification - must look like xterm-256color for color support
        env["TERM"]           = "xterm-256color"
        env["TERM_PROGRAM"]   = "vscode"
        env["COLORTERM"]      = "truecolor"
        env["TERM_PROGRAM_VERSION"] = "1.85.0"

        # Enable colors in common tools
        env["CLICOLOR"]       = "1"
        env["CLICOLOR_FORCE"] = "1"
        env["FORCE_COLOR"]    = "3"
        env["GCC_COLORS"]     = "error=01;31:warning=01;35:note=01;36:caret=01;32:locus=01:quote=01"

        # Language/locale
        env.setdefault("LANG", "en_US.UTF-8")
        env.setdefault("LC_ALL", "en_US.UTF-8")

        # Pager
        env["PAGER"] = "less"
        env["LESS"]  = "-R -F -X"

        return env

    # ─────────────────────────────────────────────
    # Context manager support
    # ─────────────────────────────────────────────

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()
