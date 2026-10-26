"""SDK-style Pro queries using the same bounded transport as settings checks.

The configured URL is a complete endpoint, not a prefix for /{api_name}.
No Tushare SDK globals or process-wide proxy settings are changed.
"""
from __future__ import annotations

from functools import partial
import re
from typing import Any, Callable, Protocol

import pandas as pd

from deck.data_settings import DataSettings, PinnedTransport, _url, resolve_endpoint
from deck.model_settings import SettingsError


class ProTransport(Protocol):
    def __call__(self, endpoint: str, payload: dict[str, Any], resolved_ip: str,
                 timeout: float, max_response: int) -> dict[str, Any]: ...


class ProClient:
    def __init__(self, token: str, endpoint: str, allow_insecure_http: bool = False, *,
                 transport: ProTransport | None = None, resolver: Callable[..., Any] | None = None) -> None:
        self._token = token
        self._endpoint = endpoint
        self._allow_http = allow_insecure_http is True
        self._transport = transport or PinnedTransport()
        self._resolver = resolver

    def query(self, api_name: str, fields: str = '', **kwargs: Any) -> pd.DataFrame:
        if not isinstance(api_name, str) or not re.fullmatch(r'[a-z][a-z0-9_]*', api_name):
            raise SettingsError('INVALID_REQUEST', 400)
        if not isinstance(fields, str) or not isinstance(self._token, str) or not self._token:
            raise SettingsError('INVALID_REQUEST', 400)
        parsed = _url(self._endpoint)
        if parsed.scheme == 'http' and not self._allow_http:
            raise SettingsError('INSECURE_HTTP_CONFIRMATION_REQUIRED', 400)
        ip = resolve_endpoint(self._endpoint, self._resolver)
        payload = {'api_name': api_name, 'token': self._token, 'params': kwargs, 'fields': fields}
        try:
            # Runtime bulk queries need more room than the settings page's 3-row
            # checks, but retain an absolute deadline and a finite byte cap.
            result = self._transport(self._endpoint, payload, ip, 10, 16 * 1024 * 1024)
            status = DataSettings._status(result)
            if status not in ('available', 'empty'):
                code = {'credentials': 'CREDENTIALS', 'permission': 'PERMISSION',
                        'rate_limited': 'RATE_LIMITED'}.get(status, 'UPSTREAM_ERROR')
                raise SettingsError(code, 502)
            data = result['data']
            columns, rows = data.get('fields'), data['items']
            if (not isinstance(columns, list) or not all(isinstance(c, str) and c for c in columns)
                    or len(set(columns)) != len(columns)
                    or any(not isinstance(row, list) or len(row) != len(columns) for row in rows)):
                raise SettingsError('UPSTREAM_ERROR', 502)
            return pd.DataFrame(rows, columns=columns)
        except SettingsError:
            raise
        except (OSError, TimeoutError):
            raise SettingsError('NETWORK', 502) from None
        except Exception:
            raise SettingsError('UPSTREAM_ERROR', 502) from None

    def __getattr__(self, name: str) -> Callable[..., pd.DataFrame]:
        if not re.fullmatch(r'[a-z][a-z0-9_]*', name):
            raise AttributeError(name)
        return partial(self.query, name)
