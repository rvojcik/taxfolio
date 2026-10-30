"""Client for the IBKR Flex Web Service (version 3).

1. ``SendRequest?t=<token>&q=<query id>&v=3`` asks IBKR to generate the statement and returns a
   reference code (and the URL to collect it from).
2. ``GetStatement?t=<token>&q=<reference code>&v=3`` returns the statement XML; while it is still
   being generated IBKR answers with error 1019, so we poll.

Without ``fd``/``td`` the period is the one configured in the Flex Query itself (e.g. "Last 365
Calendar Days"); with them IBKR returns that date range instead (at most 365 days, ``yyyyMMdd``).
"""

from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from taxfolio.i18n import N_, _

BASE_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"
USER_AGENT = "taxfolio/0.1"
MAX_RANGE_DAYS = 365  # IBKR limit for one request
# A dropped connection or a DNS hiccup is retried after these pauses (seconds)
NETWORK_RETRY_DELAYS = (3.0, 10.0)

RETRYABLE = {
    "1009": N_("server je přetížen"),
    "1018": N_("příliš mnoho požadavků (limit IBKR: 1 za sekundu, 10 za minutu)"),
    "1019": N_("výpis se generuje"),
}
HINTS = {
    "1012": N_("Token vypršel – vygenerujte nový v Client Portalu (Settings → Flex Web Service)."),
    "1015": N_("Token je neplatný – zkontrolujte jej v Nastavení."),
    "1014": N_("Query ID je neplatné – zkontrolujte číslo Flex Query v Nastavení."),
    "1020": N_("IBKR požadavek neověřil – zkontrolujte token a Query ID."),
}

HttpGet = Callable[[str], bytes]


class FlexWebError(RuntimeError):
    def __init__(self, code: str, message: str):
        hint = HINTS.get(code, "")
        text = _("IBKR Flex chyba {code}: {message}").format(code=code, message=message)
        super().__init__(text + (f" {_(hint)}" if hint else ""))
        self.code = code


@dataclass(frozen=True)
class _Reply:
    status: str
    reference: str = ""
    url: str = ""
    code: str = ""
    message: str = ""


# Seconds without an answer before a request is given up (and a Stop takes effect at the latest)
HTTP_TIMEOUT = 30


def http_get(url: str, timeout: int = HTTP_TIMEOUT) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 – fixed https host
        data: bytes = resp.read()
        return data


def _get_with_retry(
    get: HttpGet, url: str, sleep: Callable[[float], None], progress: Callable[[str], None]
) -> bytes:
    """``get`` that survives short network outages; a lasting one becomes a readable FlexWebError."""
    for attempt, delay in enumerate((*NETWORK_RETRY_DELAYS, None), start=1):
        try:
            return get(url)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            reason = getattr(exc, "reason", exc)
            # a 4xx answer will not change on retry; a 5xx or no answer at all may
            if (isinstance(exc, urllib.error.HTTPError) and exc.code < 500) or delay is None:
                host = urllib.parse.urlsplit(url).hostname or url
                raise FlexWebError(
                    "NET",
                    _(
                        "nelze se spojit se serverem IBKR ({host}): {reason}. Zkontrolujte připojení "
                        "k internetu a zkuste to znovu."
                    ).format(host=host, reason=reason),
                ) from exc
            progress(
                _(
                    "Spojení s IBKR selhalo ({reason}), zkouším znovu za {seconds} s ({attempt}/{total})…"
                ).format(reason=reason, seconds=int(delay), attempt=attempt, total=len(NETWORK_RETRY_DELAYS))
            )
            sleep(delay)
    raise AssertionError("unreachable")


def _parse_reply(body: bytes) -> _Reply | None:
    """Parse a FlexStatementResponse; ``None`` means the body is the statement itself."""
    text = body.lstrip()
    if text.startswith(b"<?xml"):
        text = text[text.find(b"?>") + 2 :].lstrip()
    if text.startswith(b"<FlexQueryResponse"):
        return None
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise FlexWebError("XML", _("neočekávaná odpověď IBKR ({detail})").format(detail=exc)) from exc
    if root.tag != "FlexStatementResponse":
        raise FlexWebError("XML", _("neočekávaná odpověď IBKR ({detail})").format(detail=f"<{root.tag}>"))
    return _Reply(
        status=root.findtext("Status", ""),
        reference=root.findtext("ReferenceCode", ""),
        url=root.findtext("Url", ""),
        code=root.findtext("ErrorCode", ""),
        message=root.findtext("ErrorMessage", ""),
    )


def fetch_statement(
    token: str,
    query_id: str,
    *,
    get: HttpGet = http_get,
    sleep: Callable[[float], None] = time.sleep,
    poll_interval: float = 5.0,
    max_wait: float = 300.0,
    progress: Callable[[str], None] = lambda _msg: None,
    from_date: date | None = None,
    to_date: date | None = None,
) -> bytes:
    """Run the Flex Query and return the statement XML (bytes).

    ``from_date``/``to_date`` (both or neither) override the period saved in the query.
    """
    if not token or not query_id:
        raise FlexWebError("CFG", _("chybí token nebo Query ID"))
    query: dict[str, str | int] = {"t": token, "q": query_id, "v": 3}
    if (from_date is None) != (to_date is None):
        raise FlexWebError("CFG", _("zadejte začátek i konec období"))
    if from_date is not None and to_date is not None:
        days = (to_date - from_date).days + 1
        if days < 1 or days > MAX_RANGE_DAYS:
            raise FlexWebError(
                "CFG",
                _("období {start} – {end} musí mít 1 až {limit} dní").format(
                    start=from_date, end=to_date, limit=MAX_RANGE_DAYS
                ),
            )
        query.update(fd=f"{from_date:%Y%m%d}", td=f"{to_date:%Y%m%d}")
    params = urllib.parse.urlencode(query)
    progress(_("Žádám IBKR o vygenerování výpisu…"))
    first = _get_with_retry(get, f"{BASE_URL}/SendRequest?{params}", sleep, progress)
    reply = _parse_reply(first)
    if reply is None:  # the statement came back right away
        return first
    if reply.status != "Success" or not reply.reference:
        raise FlexWebError(reply.code or "?", reply.message or reply.status)

    statement_url = reply.url or f"{BASE_URL}/GetStatement"
    params = urllib.parse.urlencode({"t": token, "q": reply.reference, "v": 3})
    waited = 0.0
    while True:
        sleep(poll_interval)
        waited += poll_interval
        body = _get_with_retry(get, f"{statement_url}?{params}", sleep, progress)
        reply = _parse_reply(body)
        if reply is None:
            progress(_("Výpis stažen ({size} kB).").format(size=len(body) // 1024))
            return body
        if reply.code in RETRYABLE and waited < max_wait:
            progress(
                _("Čekám – {reason} ({seconds} s)…").format(
                    reason=_(RETRYABLE[reply.code]), seconds=int(waited)
                )
            )
            continue
        raise FlexWebError(reply.code or "?", reply.message or reply.status)
