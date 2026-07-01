import logging
import os
from datetime import datetime


class PixelKitLogger:
    """Logging framework that writes to both Python logging and the GUI console."""

    def __init__(self, console_callback=None, log_dir=None):
        self.console_callback = console_callback
        self._logger = logging.getLogger("PixelKit")
        self._logger.setLevel(logging.DEBUG)

        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(
                log_dir,
                f"pixelkit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            )
            fh = logging.FileHandler(log_path, encoding='utf-8')
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(formatter)
            self._logger.addHandler(fh)

        ch = logging.StreamHandler()
        ch.setLevel(logging.WARNING)
        ch.setFormatter(formatter)
        self._logger.addHandler(ch)

    @staticmethod
    def _sanitise(text):
        import re
        return re.sub(
            r'[A-Z]:\\(?:[^\\]+\\)*?_MEI\d+\\',
            r'[temp]\\', text
        )

    def _console(self, text, tag=None):
        if self.console_callback:
            self.console_callback(self._sanitise(text), tag)

    def debug(self, text):
        self._logger.debug(text.rstrip('\n'))

    def info(self, text):
        s = self._sanitise(text)
        self._logger.info(s.rstrip('\n'))
        self._console(s)

    def status(self, text):
        s = self._sanitise(text)
        self._logger.info("STATUS: " + s.rstrip('\n'))
        self._console(s, "status")

    def error(self, text):
        s = self._sanitise(text)
        self._logger.error(s.rstrip('\n'))
        self._console(s, "error")

    def command_output(self, text):
        s = self._sanitise(text)
        self._logger.debug("CMD: " + s.rstrip('\n'))
        self._console(s, "command_output")
