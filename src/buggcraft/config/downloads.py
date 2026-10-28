"""Shared limits for file downloads, read when a new download starts."""

DEFAULT_CONCURRENCY = 32
CONCURRENCY_KEY = 'downloads.concurrency'


def normalize_concurrency(value):
    try:
        if isinstance(value, bool):
            return DEFAULT_CONCURRENCY
        return max(1, min(64, int(value)))
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_CONCURRENCY


def download_concurrency(settings=None):
    if settings is None:
        from config.settings import get_settings_manager
        settings = get_settings_manager()
    return normalize_concurrency(settings.get_setting(CONCURRENCY_KEY, DEFAULT_CONCURRENCY))
