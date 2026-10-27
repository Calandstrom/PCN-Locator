import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from tqdm import tqdm
from urllib3.util.retry import Retry


GEOCODE_URL = ""
PLACES_TEXTSEARCH_URL = ""

RESULT_FIELDS = [
    "geocode_status",
    "geocode_error_message",
    "geocode_source",
    "geocode_result_count",
    "geocode_formatted_address",
    "geocode_place_id",
    "geocode_location_type",
    "geocode_partial_match",
    "geocode_types",
    "Latitude",
    "Longitude",
]





def resolve_api_key(cli_api_key: Optional[str]) -> Optional[str]:
    if cli_api_key and cli_api_key.strip():
        return cli_api_key.strip()
    env_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if env_key and env_key.strip():
        return env_key.strip()
    return None

def build_session(max_retries: int = 5) -> requests.Session:
    session = requests.Session()
    retry_strategy = Retry(
        total=max_retries,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def load_cache(cache_path: str) -> Dict[str, Dict[str, Any]]:
    if not cache_path:
        return {}
    if not os.path.exists(cache_path):
        return {}
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            # query -> record
            return {str(k): v for k, v in data.items() if isinstance(v, dict)}
    except Exception:
        pass
    return {}


def save_cache(cache_path: str, cache: Dict[str, Dict[str, Any]]) -> None:
    if not cache_path:
        return
    os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
    tmp_path = cache_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, cache_path)


def normalize_query(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if s.lower() == "nan":
        return ""
    return s


def _parse_geocode_response(payload: Dict[str, Any], source: str) -> Dict[str, Any]:
    status = payload.get("status")
    error_message = payload.get("error_message")
    results = payload.get("results") or []

    # Add helpful hint for ZERO_RESULTS
    if status == "ZERO_RESULTS" and not error_message:
        error_message = "No results found. Try adding location context (e.g., city, country) to the query or use --append flag."

    record: Dict[str, Any] = {
        "geocode_status": status,
        "geocode_error_message": error_message,
        "geocode_source": source,
        "geocode_result_count": len(results) if isinstance(results, list) else None,
        "geocode_formatted_address": None,
        "geocode_place_id": None,
        "geocode_location_type": None,
        "geocode_partial_match": None,
        "geocode_types": None,
        "Latitude": None,
        "Longitude": None,
    }

    if status != "OK" or not isinstance(results, list) or not results:
        return record

    top = results[0] or {}
    geom = (top.get("geometry") or {}) if isinstance(top, dict) else {}
    loc = (geom.get("location") or {}) if isinstance(geom, dict) else {}
    record["Latitude"] = loc.get("lat")
    record["Longitude"] = loc.get("lng")
    record["geocode_formatted_address"] = top.get("formatted_address")
    record["geocode_place_id"] = top.get("place_id")
    record["geocode_location_type"] = (geom.get("location_type") if isinstance(geom, dict) else None)
    record["geocode_partial_match"] = top.get("partial_match")
    types = top.get("types")
    if isinstance(types, list):
        record["geocode_types"] = ";".join(str(t) for t in types)
    return record


def geocode_query(
    session: requests.Session,
    api_key: str,
    query: str,
    *,
    components: Optional[str] = None,
    region: Optional[str] = None,
    language: Optional[str] = None,
    timeout_s: float = 20.0,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {"address": query, "key": api_key}
    if components:
        params["components"] = components
    if region:
        params["region"] = region
    if language:
        params["language"] = language

    #######################################################################
    prepared = requests.Request('GET', GEOCODE_URL, params=params).prepare()
    print(f"Request URL: {prepared.url}")



    r = session.get(GEOCODE_URL, params=params, timeout=timeout_s)
    payload = r.json()
    return _parse_geocode_response(payload, source="geocode")


def places_textsearch_query(
    session: requests.Session,
    api_key: str,
    query: str,
    *,
    region: Optional[str] = None,
    language: Optional[str] = None,
    timeout_s: float = 20.0,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {"query": query, "key": api_key}
    if region:
        params["region"] = region
    if language:
        params["language"] = language

    r = session.get(PLACES_TEXTSEARCH_URL, params=params, timeout=timeout_s)
    payload = r.json()


    ################################################
    print(f"Places search called with: {query}")  # add this

    # Normalize Places response into the same record schema
    status = payload.get("status")
    error_message = payload.get("error_message")
    results = payload.get("results") or []

    # Add helpful hint for ZERO_RESULTS
    if status == "ZERO_RESULTS" and not error_message:
        error_message = "No results found. Try adding location context (e.g., city, country) to the query or use --append flag."

    record: Dict[str, Any] = {
        "geocode_status": status,
        "geocode_error_message": error_message,
        "geocode_source": "places_textsearch",
        "geocode_result_count": len(results) if isinstance(results, list) else None,
        "geocode_formatted_address": None,
        "geocode_place_id": None,
        "geocode_location_type": None,
        "geocode_partial_match": None,
        "geocode_types": None,
        "Latitude": None,
        "Longitude": None,
    }

    if status != "OK" or not isinstance(results, list) or not results:
        return record

    top = results[0] or {}
    geom = (top.get("geometry") or {}) if isinstance(top, dict) else {}
    loc = (geom.get("location") or {}) if isinstance(geom, dict) else {}
    record["Latitude"] = loc.get("lat")
    record["Longitude"] = loc.get("lng")
    record["geocode_formatted_address"] = top.get("formatted_address")
    record["geocode_place_id"] = top.get("place_id")
    types = top.get("types")
    if isinstance(types, list):
        record["geocode_types"] = ";".join(str(t) for t in types)
    return record


def geocode_with_backoff(
    session: requests.Session,
    api_key: str,
    query: str,
    *,
    components: Optional[str],
    region: Optional[str],
    language: Optional[str],
    timeout_s: float,
    max_attempts: int,
    min_delay_s: float,
    use_places_fallback: bool,
) -> Dict[str, Any]:
    """
    Geocode a query with automatic handling for PCN names and organization names.
    For queries that look like PCN names (contain "PCN"), automatically tries:
    1. Places Text Search (better for business/organization names)
    2. Multiple query variations with location context (", UK", ", United Kingdom")
    3. Standard Geocoding API as fallback
    """
    # Detect if this looks like a PCN or organization name
    is_pcn_like = "PCN" in query.upper() or (
        len(query.split()) <= 4 and not any(char.isdigit() for char in query)
    )
    
    # Build query variations for PCN-like queries
    query_variations = [query]
    if is_pcn_like:
        # Try with location context - prioritize UK if country is GB or region suggests UK
        if components and "country:GB" in components:
            query_variations.extend([f"{query}, UK", f"{query}, United Kingdom"])
        elif region and region.lower() in ("uk", "gb", "united kingdom"):
            query_variations.extend([f"{query}, UK", f"{query}, United Kingdom"])
        else:
            # Default to UK context for PCN names
            query_variations.extend([f"{query}, UK", f"{query}, United Kingdom"])
    
    # For PCN-like queries, try Places Text Search first (better for business names)
    # Always try Places Text Search for PCN names, regardless of the flag
    if is_pcn_like:
        for variation in query_variations:
            try:
                result = places_textsearch_query(
                    session, api_key, variation, region=region, language=language, timeout_s=timeout_s
                )
                if result.get("geocode_status") == "OK":
                    return result
                time.sleep(max(min_delay_s, 0.0))
            except Exception:
                continue
    
    # Try standard Geocoding API with query variations
    backoff = max(min_delay_s, 0.0)
    last: Optional[Dict[str, Any]] = None

    for variation in query_variations:
        for attempt in range(1, max_attempts + 1):
            try:
                last = geocode_query(
                    session,
                    api_key,
                    variation,
                    components=components,
                    region=region,
                    language=language,
                    timeout_s=timeout_s,
                )
            except Exception as e:
                if variation == query_variations[-1]:  # Only return error on last variation
                    return {
                        "geocode_status": "REQUEST_ERROR",
                        "geocode_error_message": str(e),
                        "geocode_source": "geocode",
                        "geocode_result_count": None,
                        "geocode_formatted_address": None,
                        "geocode_place_id": None,
                        "geocode_location_type": None,
                        "geocode_partial_match": None,
                        "geocode_types": None,
                        "Latitude": None,
                        "Longitude": None,
                    }
                continue

            if last.get("geocode_status") == "OK":
                return last

            # Geocoding API signals rate-limit via JSON status, not always HTTP 429
            if last.get("geocode_status") in {"OVER_QUERY_LIMIT"} and attempt < max_attempts:
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)
                continue

            break  # Move to next variation
        
        if last and last.get("geocode_status") == "OK":
            break
        time.sleep(max(min_delay_s, 0.0))

    # Final fallback: Places Text Search if not already tried and enabled
    if use_places_fallback and not is_pcn_like and (last or {}).get("geocode_status") in {"ZERO_RESULTS"}:
        try:
            return places_textsearch_query(
                session, api_key, query, region=region, language=language, timeout_s=timeout_s
            )
        except Exception as e:
            if last is None:
                last = {}
            last = dict(last)
            last["geocode_source"] = "geocode"
            last["geocode_error_message"] = (last.get("geocode_error_message") or "") + f" | places_error={e}"
            return last

    return last or {
        "geocode_status": "UNKNOWN_ERROR",
        "geocode_error_message": None,
        "geocode_source": "geocode",
        "geocode_result_count": None,
        "geocode_formatted_address": None,
        "geocode_place_id": None,
        "geocode_location_type": None,
        "geocode_partial_match": None,
        "geocode_types": None,
        "Latitude": None,
        "Longitude": None,
    }


@dataclass
class Args:
    input: str
    output: str
    sheet: Optional[str]
    column: Optional[str]
    api_key: Optional[str]
    append: str
    country: Optional[str]
    region: Optional[str]
    language: Optional[str]
    cache: str
    min_delay: float
    timeout: float
    attempts: int
    limit: Optional[int]
    use_places_fallback: bool


def parse_args() -> Args:
    p = argparse.ArgumentParser(
        description="Geocode family practice clinic names/addresses from the first Excel column and write Latitude/Longitude to a new Excel file."
    )
    p.add_argument(
        "--input",
        default="Family_Practice.xlsx",
        help="Input Excel file path (default: Family_Practice.xlsx)",
    )
    p.add_argument("--output", default="", help="Output Excel file path. Default: <input>_geocoded.xlsx")
    p.add_argument("--sheet", default=None, help="Excel sheet name. Default: first sheet")
    p.add_argument(
        "--column",
        default=None,
        help="Column name or 0-based index to geocode. Default: first column",
    )
    p.add_argument("--api-key", default=None, help="Google Maps API key. Otherwise uses env GOOGLE_MAPS_API_KEY.")
    p.add_argument(
        "--append",
        default="",
        help='Text to append to every query (e.g., ", United Kingdom") to improve matching.',
    )
    p.add_argument(
        "--country",
        default=None,
        help="Restrict results to a country code (e.g., GB). Implemented as Geocoding 'components=country:XX'.",
    )
    p.add_argument("--region", default=None, help="Geocoding/Places region bias (e.g., 'uk').")
    p.add_argument("--language", default=None, help="Response language (e.g., 'en').")
    p.add_argument("--cache", default="geocode_cache.json", help="Cache file path (json).")
    p.add_argument("--min-delay", type=float, default=0.1, help="Minimum delay between API calls (seconds).")
    p.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout per request (seconds).")
    p.add_argument("--attempts", type=int, default=5, help="Max attempts for OVER_QUERY_LIMIT backoff.")
    p.add_argument("--limit", type=int, default=None, help="Limit number of unique queries to geocode (debug).")
    p.add_argument(
        "--use-places-fallback",
        action="store_true",
        help="If Geocoding returns ZERO_RESULTS, try Places Text Search (requires Places API enabled).",
    )

    ns = p.parse_args()
    output = ns.output
    if not output:
        base, ext = os.path.splitext(ns.input)
        output = f"{base}_geocoded.xlsx"

    return Args(
        input=ns.input,
        output=output,
        sheet=ns.sheet,
        column=ns.column,
        api_key=ns.api_key,
        append=ns.append,
        country=ns.country,
        region=ns.region,
        language=ns.language,
        cache=ns.cache,
        min_delay=ns.min_delay,
        timeout=ns.timeout,
        attempts=ns.attempts,
        limit=ns.limit,
        use_places_fallback=ns.use_places_fallback,
    )


def main() -> int:
    args = parse_args()

    # ── API key ───────────────────────────────────────────────────────────────
    api_key = input("Enter your Google API key: ").strip()
    if not api_key:
        raise SystemExit("No API key provided.")
    print(f"Key length: {len(api_key)}, repr: {repr(api_key[:10])}...")

    
    csv_file = input("Enter the input CSV file: ").strip()
    if not csv_file:
        raise SystemExit("No CSV file provided")
    
    col_name = input("Enter the column name for the hospital in your CSV file: ")
    if not col_name:
        raise SystemExit("No column provided")

    # ── Load unmatched PCNs directly from CSV — no Excel conversion needed ────
    df = pd.read_csv(csv_file)
    if df.empty:
        raise SystemExit(".csv is empty — nothing to geocode.")

    print(f"PCNs to geocode: {len(df)}")

    # ── Build queries ─────────────────────────────────────────────────────────
    if col_name not in df.columns:
        raise SystemExit(
            f"Column '{col_name}' not found. Available: {list(df.columns)}"
        )

    df["_geocode_query"] = df[col_name].map(normalize_query)
    unique_queries = (df["_geocode_query"]
        [df["_geocode_query"] != ""]
        .drop_duplicates()
    )

    print(f"Unique PCNs     : {len(unique_queries)}")

    # ── Load existing cache ───────────────────────────────────────────────────
    cache          = load_cache(args.cache)
    already_cached = sum(1 for q in unique_queries if q in cache)
    print(f"Already cached  : {already_cached}")
    print(f"Needs API call  : {len(unique_queries) - already_cached}")

    # ── Geocode loop ──────────────────────────────────────────────────────────
    session = build_session(max_retries=5)
    records = []
    calls   = 0

    for q in tqdm(list(unique_queries), desc="Geocoding PCNs"):
        if q in cache:
            records.append({"_geocode_query": q, **cache[q]})
            continue

        rec = geocode_with_backoff(
            session,
            api_key,
            q,
            components="country:GB",
            region="uk",
            language="en",
            timeout_s=20.0,
            max_attempts=5,
            min_delay_s=0.1,
            use_places_fallback=True,
        )
        cache[q] = rec
        records.append({"_geocode_query": q, **rec})

        calls += 1
        if calls % 50 == 0:
            save_cache(args.cache, cache)
            print(f"  Saved progress — {calls} geocoded so far")

        time.sleep(0.1)

    # ── Final cache save ──────────────────────────────────────────────────────
    save_cache(args.cache, cache)

    # ── Merge results back into dataframe ─────────────────────────────────────
    results_df = pd.DataFrame(records)
    out_df     = (df
        .merge(results_df, on="_geocode_query", how="left")
        .drop(columns=["_geocode_query"])
    )

    # ── Save final output as CSV — no Excel needed ────────────────────────────
    output_path = 'pcn_newly_geocoded.csv'
    out_df.to_csv(output_path, index=False)

    # ── Summary ───────────────────────────────────────────────────────────────
    ok_count   = int((out_df["geocode_status"] == "OK").sum())
    fail_count = len(out_df) - ok_count

    print(f"\nDone!")
    print(f"  ✓ Geocoded OK : {ok_count}")
    print(f"  ✗ Failed      : {fail_count}")
    print(f"  Output        : {output_path}")
    print(f"  Cache         : {args.cache}")

    if fail_count > 0:
        failed = out_df[out_df['geocode_status'] != 'OK'][[col_name, 'geocode_status']]
        print(f"\nFailed PCNs:")
        print(failed.to_string(index=False))

    return 0




if __name__ == "__main__":
    raise SystemExit(main())

