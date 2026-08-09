"""日志配置，基于 structlog"""

import logging
import structlog


def setup_logging(debug: bool = True) -> None:
    """配置 structlog：开发环境用彩色控制台，生产环境输出 JSON"""
    level = logging.DEBUG if debug else logging.INFO

    logging.basicConfig(format="%(message)s", level=level)

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(colors=True) if debug else structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
