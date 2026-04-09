import httpx


def build_sync_httpx_client(
    *,
    timeout: httpx.Timeout | float | None = None,
    follow_redirects: bool = False,
) -> httpx.Client:
    # httpx 0.28 does not accept proxy=False; use proxy=None and trust_env=False
    # to fully disable explicit and environment-provided proxies.
    return httpx.Client(
        timeout=timeout,
        follow_redirects=follow_redirects,
        proxy=None,
        trust_env=False,
    )


def build_async_httpx_client(
    *,
    timeout: httpx.Timeout | float | None = None,
    follow_redirects: bool = False,
) -> httpx.AsyncClient:
    # httpx 0.28 does not accept proxy=False; use proxy=None and trust_env=False
    # to fully disable explicit and environment-provided proxies.
    return httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=follow_redirects,
        proxy=None,
        trust_env=False,
    )
