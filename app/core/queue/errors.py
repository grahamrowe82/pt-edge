class PermanentTaskError(Exception):
    """Error that will never resolve on retry. Fails immediately, no retries."""
    pass
