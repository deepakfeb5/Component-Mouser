
# ============================================================
# Mouser BOM Sourcing Dashboard (Mouser-only, production-safe)
# - Secure TLS (no verify=False)
# - Corporate CA friendly (pip-system-certs / REQUESTS_CA_BUNDLE)
# - Per-minute rate limiting + retries/backoff
# - Real endpoint health check
# - CSV upload, total cost, results download
# ============================================================

import os
import time
import json
import random
from typing import Tuple, List, Optional, Dict, Any

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ------------------------------------------------------------
# Streamlit App Config
# ------------------------------------------------------------
st.set_page_config(page_title="Mouser BOM Tool", layout="wide")
st.title("🔍 Mouser BOM Sourcing Dashboard")

load_dotenv()

# ------------------------------------------------------------
# Timeouts & Retry Settings
# ------------------------------------------------------------
CONNECT_TIMEOUT = float(os.getenv("CONNECT_TIMEOUT", "5"))
READ_TIMEOUT = float(os.getenv("READ_TIMEOUT", "45"))
TIMEOUT = (CONNECT_TIMEOUT, READ_TIMEOUT)

MAX_RETRIES = int(os.getenv("MAX_RETRIES", "5"))
BACKOFF_BASE = float(os.getenv("BACKOFF_BASE", "1.2"))
BACKOFF_CAP = float(os.getenv("BACKOFF_CAP", "30"))

# ------------------------------------------------------------
# CREATE GLOBAL SESSION (Secure, Correct)
# ------------------------------------------------------------
session = requests.Session()

# If your corporate network requires proxy, allow it explicitly
session.trust_env = os.getenv("TRUST_ENV", "false").lower() == "true"

# Corporate CA support (preferred):
# - If you installed 'pip-system-certs', Python will use the Windows system store.
# - If REQUESTS_CA_BUNDLE / SSL_CERT_FILE is provided, honor it.
bundle = os.getenv("REQUESTS_CA_BUNDLE") or os.getenv("SSL_CERT_FILE")
if bundle and os.path.exists(bundle):
    session.verify = bundle
# else: default trust (certifi + truststore on modern pip)

# Robust retries for transient network and 429/5xx
retry = Retry(
    total=MAX_RETRIES,
    connect=3,
    read=3,
    status=3,
    backoff_factor=0.8,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=("GET", "POST", "HEAD"),
)
adapter = HTTPAdapter(max_retries=retry)
session.mount("https://", adapter)
session.mount("http://", adapter)

# ------------------------------------------------------------
# Rate Limiter
# ------------------------------------------------------------
class RateLimiter:
    def __init__(self, calls_per_min: int):
        self.min_interval = 60.0 / max(calls_per_min, 1)
        self.next_ok = time.monotonic()

    def wait(self):
        now = time.monotonic()
        if now < self.next_ok:
            time.sleep(self.next_ok - now)
        self.next_ok = time.monotonic() + self.min_interval

MOUSER_RATE = int(os.getenv("MOUSER_CALLS_PER_MINUTE", "10"))
rate_limiter = RateLimiter(MOUSER_RATE)

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def parse_price(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(str(value).replace("$", "").replace(",", "").strip())
    except Exception:
        return None

def compute_total(price: Optional[str], qty: int) -> Optional[float]:
    p = parse_price(price)
    return round(p * qty, 4) if p is not None else None

# ============================================================
# Mouser Client
# ============================================================
class MouserClient:
    SEARCH_URL = "https://api.mouser.com/api/v1/search/partnumber"

    def __init__(self, api_key: Optional[str]):
        self.api_key = (api_key or "").strip()
        # Simple in-memory cache { mpn -> (data, alternates, error) }
        self.cache: Dict[str, Tuple[Optional[Dict[str, Any]], List[str], Optional[str]]] = {}

    def _backoff_sleep(self, attempt: int):
        # Exponential backoff with jitter
        delay = min(BACKOFF_CAP, (BACKOFF_BASE ** attempt)) + random.random() * 0.25
        time.sleep(delay)

    def _post_once(self, mpn: str) -> requests.Response:
        rate_limiter.wait()
        return session.post(
            self.SEARCH_URL,
            params={"apiKey": self.api_key},
            json={"SearchByPartRequest": {"mouserPartNumber": mpn}},
            timeout=TIMEOUT,
        )

    def search_part(self, mpn: str) -> Tuple[Optional[Dict], List[str], Optional[str]]:
        """
        Returns (main_data, alternates, error).

        main_data = {
            "price": str|None,
            "manufacturer": str|None,
            "stock": str|None,
            "lifecycle": str|None
        }
        """
        key = (mpn or "").strip()
        if key in self.cache:
            return self.cache[key]

        if not self.api_key:
            result = (None, [], "Missing MOUSER_API_KEY")
            self.cache[key] = result
            return result

        last_exc: Optional[Exception] = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self._post_once(key)
            except Exception as e:
                last_exc = e
                self._backoff_sleep(attempt)
                continue

            if resp.status_code == 200:
                try:
                    data = resp.json()
                except json.JSONDecodeError:
                    result = (None, [], "Invalid JSON response from Mouser")
                    self.cache[key] = result
                    return result

                parts = data.get("SearchResults", {}).get("Parts", []) or []
                if not parts:
                    result = (None, [], "No results")
                    self.cache[key] = result
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
                    "manufacturer": main.get("Manufacturer"),
                    "stock": main.get("Availability"),
                    "lifecycle": main.get("LifecycleStatus"),
                }
                result = (main_data, alternates, None)
                self.cache[key] = result
                return result

            # Mouser rate-limit signals can be 429 or 403 with JSON body
            if resp.status_code in (403, 429):
                try:
                    body = resp.json()
                except Exception:
                    body = {}
                err_list = body.get("Errors") or []
                err_code = (err_list[0] or {}).get("Code") if err_list else None
                if err_code == "TooManyRequests":
                    self._backoff_sleep(attempt)
                    continue

            # Other non-200 responses: surface message/snippet
            err_snippet = (resp.text or "").strip()[:300]
            result = (None, [], f"HTTP {resp.status_code}: {err_snippet}")
            self.cache[key] = result
            return result

        # If we exhausted retries
        if last_exc is not None:
            result = (None, [], f"Network error: {last_exc}")
            self.cache[key] = result
            return result

        result = (None, [], "Request failed after retries")
        self.cache[key] = result
        return result

# ============================================================
# Network Diagnostic (real API path)
# ============================================================
def network_test() -> Tuple[bool, str]:
    api_key = os.getenv("MOUSER_API_KEY", "").strip()
    if not api_key:
        return False, "MOUSER_API_KEY not set"
    try:
        rate_limiter.wait()
        r = session.post(
            MouserClient.SEARCH_URL,
            params={"apiKey": api_key},
            json={"SearchByPartRequest": {"mouserPartNumber": "SN74HC00N"}},
            timeout=TIMEOUT,
        )
        if r.status_code == 200:
            return True, f"API ok (200) in {r.elapsed.total_seconds():.2f}s"
        return False, f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return False, str(e)

# ============================================================
# UI: Network Diagnostic
# ============================================================
with st.expander("🔧 Network Diagnostic"):
    ok, message = network_test()
    if ok:
        st.success(f"Mouser API reachable: {message}")
    else:
        st.error(f"Network Error: {message}")
        st.info(
            "If your company inspects TLS, install 'pip-system-certs' in your venv "
            "or set REQUESTS_CA_BUNDLE to a combined CA file."
        )
        st.stop()

# ============================================================
# Streamlit UI: Upload & Process BOM
# ============================================================
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
    df = df.dropna(subset=["Quantity"])
    df["Quantity"] = df["Quantity"].astype(int)
    df["PartNumber"] = df["PartNumber"].astype(str).str.strip()

    results: List[Dict[str, Any]] = []
    total_cost: float = 0.0

    progress = st.progress(0.0)
    n = len(df)

    for i, (_, row) in enumerate(df.iterrows(), start=1):
        mpn = row["PartNumber"]
        qty = int(row["Quantity"])

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
    st.info("Upload a CSV to begin.")

# Footer tips
with st.expander("ℹ️ Help & Tips"):
    st.markdown(
        "- **Rate limiting**: ~{} calls/min (min interval = {:.2f}s)\n"
        "- **Retries & Backoff**: Transient errors (429/5xx) retried with exponential backoff.\n"
        "- **Proxy/TLS**: Set `TRUST_ENV=true` to inherit corporate proxy. "
        "If TLS inspection is used, install `pip-system-certs` or set `REQUESTS_CA_BUNDLE`.\n"
        "- **Caching**: Duplicate MPNs in the same run are served from in‑memory cache."
        .format(MOUSER_RATE, rate_limiter.min_interval)
    )
