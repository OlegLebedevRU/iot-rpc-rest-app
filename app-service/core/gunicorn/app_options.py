from .logger import GunicornLogger


def get_app_options(
    host: str,
    port: int,
    timeout: int,
    workers: int,
    log_level: str,
    *,
    camera_runtime_enabled: bool = False,
) -> dict:
    return {
        "accesslog": "-",
        "errorlog": "-",
        "bind": f"{host}:{port}",
        "loglevel": log_level,
        "logger_class": GunicornLogger,
        "timeout": timeout,
        "workers": workers,
        "worker_class": "uvicorn.workers.UvicornWorker",
        "keepalive": 5,
        "graceful_timeout": 15,
        # A monotonic camera issuer cannot survive its owning worker. Recycling
        # after an arbitrary HTTP request count would retire a healthy stream.
        # Actual shutdown/death still uses the existing durable takeover fences.
        "max_requests": 0 if camera_runtime_enabled else 1000,
        "max_requests_jitter": 0 if camera_runtime_enabled else 100,
    }
