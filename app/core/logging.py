import logging

from app.core.config import AppSettings
from app.core.context import get_request_id, get_trace_id


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        record.trace_id = get_trace_id()
        return True


def configure_logging(settings: AppSettings) -> None:
    level = getattr(logging, settings.observability.log_level)
    handler = logging.StreamHandler()
    handler.addFilter(RequestContextFilter())
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s service=%(name)s request_id=%(request_id)s trace_id=%(trace_id)s %(message)s"
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(handler)

