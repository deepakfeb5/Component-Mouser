import os
import time
import json
import random
import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv
from typing import Tuple, List, Optional, Dict, Any

# =====================================
# App & Env
# =====================================
st.set_page_config(page_title="Mouser BOM Tool", layout="wide")
st.title("🔍 Mouser BOM Sourcing Dashboard")

load_dotenv()

# Defaults can be tuned via env vars
CONNECT_TIMEOUT = float(os.getenv("CONNECT_TIMEOUT", "5"))
READ_TIMEOUT = float(os.getenv("READ_TIMEOUT", "45"))
TIMEOUT = (CONNECT_TIMEOUT, READ_TIMEOUT)

# Rate limiting: calls per minute (safe default)
CALLS_PER_MIN = int(os.getenv("MOUSER_CALLS_PER_MINUTE", "10"))
MIN_INTERVAL = 60.0 / max(CALLS_PER_MIN, 1)

# Backoff for transient and rate-limit retries
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "5"))
BACKOFF_BASE = float(os.getenv("BACKOFF_BASE", "1.2"))
BACKOFF_CAP = float(os.getenv("BACKOFF_CAP", "30"))

# =====================================
# Global session (ignore proxy env by default)
# =====================================
session = requests.Session()
session.trust_env = os.getenv("TRUST_ENV", "false").lower() == "true"

# Mount retries for network and HTTP 5xx/429
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

retry = Retry(
    total=MAX_RETRIES,
    connect=min(3, MAX_RETRIES),
    read=min(3, MAX_RETRIES),
    status=min(3, MAX_RETRIES),
    backoff_factor=0.8,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=("GET", "POST", "HEAD"),
    raise_on_status=False,
)
adapter = HTTPAdapter(max_retries=retry)
session.mount("https://", adapter)
session.mount("http://", adapter)

# =====================================
# Utilities
# =====================================
class RateLimiter:
    """Simple per-process rate limiter. Ensures a minimum interval between calls.
    Thread-safe enough for Streamlit's single-threaded run; uses monotonic clock.
    """
    def __init__(self, min_interval_sec: float):
        self.min_interval = max(0.0, min_interval_sec)
        self._next_ok = time.monotonic()

    def wait(self):
        now = time.monotonic()
        if now < self._next_ok:
            time.sleep(self._next_ok - now)
        self._next_ok = time.monotonic() + self.min_interval

rate_limiter = RateLimiter(MIN_INTERVAL)


def compute_total(price: Optional[str], qty: int) -> Optional[float]:
    """Compute total cost from unit price string like '$1.23'."""
    if price is None:
        return None
    try:
        p = float(str(price).replace("$", "").replace(",", "").strip())
        return round(p * qty, 4)
    except Exception:
        return None


# =====================================
# Mouser Client
# =====================================
class MouserClient:
    SEARCH_URL = "https://api.mouser.com/api/v1/search/partnumber"

    def __init__(self, api_key: Optional[str]):
        self.api_key = api_key
        # Simple in-memory cache { mpn -> (data, alternates, error) }
        self.cache: Dict[str, Tuple[Optional[Dict[str, Any]], List[str], Optional[str]]] = {}

    def _backoff_sleep(self, attempt: int):
        # exponential backoff with jitter
        delay = min(BACKOFF_CAP, (BACKOFF_BASE ** attempt))
        # add a little jitter up to 250ms
        delay += random.random() * 0.25
        time.sleep(delay)

    def _post_once(self, mpn: str) -> requests.Response:
        # rate limit BEFORE the call
        rate_limiter.wait()
        return session.post(
            self.SEARCH_URL,
            params={"apiKey": self.api_key},
            json={"SearchByPartRequest": {"mouserPartNumber": mpn}},
            timeout=TIMEOUT,
        )

    def search_part(self, mpn: str) -> Tuple[Optional[Dict], List[str], Optional[str]]:
        """Return (main_data, alternates, error). Caches by MPN and enforces rate-limit.
        Handles Mouser's 'TooManyRequests' (often 403) with backoff.
        """
        mpn_key = mpn.strip()
        if mpn_key in self.cache:
            return self.cache[mpn_key]

        if not self.api_key:
            result = (None, [], "Missing MOUSER_API_KEY")
            self.cache[mpn_key] = result
            return result

        last_exc: Optional[Exception] = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self._post_once(mpn_key)
            except Exception as e:
                last_exc = e
                self._backoff_sleep(attempt)
                continue

            # Direct success
            if resp.status_code == 200:
                try:
                    data = resp.json()
                except json.JSONDecodeError:
                    result = (None, [], "Invalid JSON response from Mouser")
                    self.cache[mpn_key] = result
                    return result

                parts = data.get("SearchResults", {}).get("Parts", [])
                if not parts:
                    result = (None, [], "No results")
                    self.cache[mpn_key] = result
                    return result

                main = parts[0]
                alternates = [
                    (p.get("ManufacturerPartNumber") or "").strip()
                    for p in parts[1:]
                    if p.get("ManufacturerPartNumber")
                ]
                price_breaks = main.get("PriceBreaks", []) or []
                unit_price = price_breaks[0].get("Price") if price_breaks else None

                main_data = {
                    "price": unit_price,
                    "lifecycle": main.get("LifecycleStatus"),
                    "manufacturer": main.get("Manufacturer"),
                    "stock": main.get("Availability"),
                }
                result = (main_data, alternates, None)
                self.cache[mpn_key] = result
                return result

            # Mouser rate-limit signals can be 429 or 403 with a JSON body
            if resp.status_code in (403, 429):
                try:
                    body = resp.json()
                except Exception:
                    body = {}
                err_list = body.get("Errors") or []
                err_code = (err_list[0] or {}).get("Code") if err_list else None
                if err_code == "TooManyRequests":
                    # escalate backoff and retry
                    self._backoff_sleep(attempt)
                    continue

            # Other non-200 responses: surface message/snippet
            err_snippet = (resp.text or "").strip()[:300]
            result = (None, [], f"HTTP {resp.status_code}: {err_snippet}")
            self.cache[mpn_key] = result
            return result

        # If we exhausted retries
        if last_exc is not None:
            result = (None, [], f"Network error: {last_exc}")
            self.cache[mpn_key] = result
            return result
        # Generic fallback
        result = (None, [], "Request failed after retries")
        self.cache[mpn_key] = result
        return result


# =====================================
# Network Diagnostic (real API path)
# =====================================
def network_test() -> Tuple[bool, str]:
    api_key = os.getenv("MOUSER_API_KEY", "").strip()
    if not api_key:
        return False, "MOUSER_API_KEY not set"
    try:
        # Make a real, tiny request to the same endpoint.
        rate_limiter.wait()  # respect limiter even during health check
        r = session.post(
            MouserClient.SEARCH_URL,
            params={"apiKey": api_key},
            json={"SearchByPartRequest": {"mouserPartNumber": "SN74HC00N"}},
            timeout=TIMEOUT,
        )
        if r.status_code == 200:
            return True, f"API ok (200) in {r.elapsed.total_seconds():.2f}s"
        # Surface a short error body for visibility
        return False, f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return False, str(e)


# =====================================
# UI: Network Diagnostic
# =====================================
with st.expander("🔧 Network Diagnostic"):
    ok, message = network_test()
    if ok:
        st.success(f"Mouser API reachable: {message}")
    else:
        st.error(f"Network Error: {message}")
        st.info(
            "If you must use a corporate proxy, set TRUST_ENV=true and configure HTTPS_PROXY.\n"
            "For TLS inspection, provide a combined CA bundle via REQUESTS_CA_BUNDLE."
        )
        st.stop()


# =====================================
# Streamlit UI: Upload & Process BOM
# =====================================
api_key = os.getenv("MOUSER_API_KEY", "").strip()
mouser_client = MouserClient(api_key)

uploaded_file = st.file_uploader(
    "Upload BOM CSV (columns: PartNumber,Quantity,Description,Manufacturer)",
    type=["csv"],
)

if uploaded_file:
    try:
        df = pd.read_csv(uploaded_file)
    except Exception as e:
        st.error(f"Failed to read CSV: {e}")
        st.stop()

    # Validate and clean
    required_cols = {"PartNumber", "Quantity"}
    missing = required_cols - set(df.columns)
    if missing:
        st.error(f"Missing required columns: {', '.join(sorted(missing))}")
        st.stop()

    df["Quantity"] = pd.to_numeric(df["Quantity"], errors="coerce")
    df = df.dropna(subset=["Quantity"])  # drop rows where Quantity is NaN
    df["Quantity"] = df["Quantity"].astype(int)

    # Normalize PartNumber column to string
    df["PartNumber"] = df["PartNumber"].astype(str).str.strip()

    results = []
    total_cost = 0.0

    progress = st.progress(0.0)
    n = len(df)

    for i, (_, row) in enumerate(df.iterrows(), start=1):
        mpn = row["PartNumber"]
        qty = int(row["Quantity"]) if not pd.isna(row["Quantity"]) else 0

        data, alternates, error = mouser_client.search_part(mpn)

        result_row = {
            "Part Number": mpn,
            "Quantity": qty,
            "Manufacturer": None,
            "Lifecycle": None,
            "Stock Info": None,
            "Unit Price": None,
            "Total Price": None,
            "Alternates": ", ".join(alternates) if alternates else None,
            "Error": None,
        }

        if error:
            result_row["Error"] = error
        else:
            result_row["Manufacturer"] = data.get("manufacturer") if data else None
            result_row["Lifecycle"] = data.get("lifecycle") if data else None
            result_row["Stock Info"] = data.get("stock") if data else None
            result_row["Unit Price"] = data.get("price") if data else None
            total_price = compute_total(data.get("price") if data else None, qty)
            result_row["Total Price"] = total_price
            if total_price:
                total_cost += total_price

        results.append(result_row)
        progress.progress(min(i / n, 1.0))

    result_df = pd.DataFrame(results)

    st.subheader("📋 Per‑Part Pricing")
    st.dataframe(result_df, use_container_width=True)

    st.subheader("📊 Total BOM Cost")
    st.metric("Total BOM Cost (Mouser)", f"${round(total_cost, 2)}")

    st.download_button(
        "Download Results CSV",
        result_df.to_csv(index=False),
        "mouser_bom_results.csv",
        "text/csv",
    )
else:
    st.info("Upload a CSV to begin (see sample in README).")

# Footer help
with st.expander("ℹ️ Help & Tips"):
    st.markdown(
        "- **Rate limiting**: This app enforces ~%d calls/min (MIN_INTERVAL=%.2fs).\n"
        "- **Retries & Backoff**: Transient errors (429/5xx) are retried with exponential backoff.\n"
        "- **Proxy/TLS**: Set TRUST_ENV=true to inherit corporate proxy env vars; add CA bundle via REQUESTS_CA_BUNDLE if TLS inspection is used.\n"
        "- **Caching**: Duplicate MPNs in the same run are served from in‑memory cache."
        % (CALLS_PER_MIN, MIN_INTERVAL)
    )
