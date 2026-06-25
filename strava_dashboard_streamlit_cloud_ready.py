import json
import time
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd
import plotly.express as px
import requests
import streamlit as st


# ============================================================
# STRAVA CONFIG
# ============================================================

CLIENT_ID = st.secrets["STRAVA_CLIENT_ID"]
CLIENT_SECRET = st.secrets["STRAVA_CLIENT_SECRET"]
REDIRECT_URI = st.secrets["STRAVA_REDIRECT_URI"]

TOKEN_FILE = Path("strava_token.json")
CACHE_FILE = Path("strava_api_cache.json")
SETTINGS_FILE = Path("strava_dashboard_settings.json")

CACHE_MAX_AGE_HOURS = 12

AUTH_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"
ATHLETE_URL = "https://www.strava.com/api/v3/athlete"
ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"


# ============================================================
# JSON HELPERS
# ============================================================

def load_json(path, default=None):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_settings():
    return load_json(SETTINGS_FILE, default={})


def save_settings():
    settings = {
        "sport_mode": st.session_state.get("sport_mode", "Radfahren"),
        "selected_gears": st.session_state.get("selected_gears", []),
        "selected_types": st.session_state.get("selected_types", []),
        "date_range": [
            str(d) for d in st.session_state.get("date_range", [])
        ],
    }
    save_json(SETTINGS_FILE, settings)


# ============================================================
# TOKEN
# ============================================================

def get_authorization_url():
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "approval_prompt": "auto",
        "scope": "read,activity:read_all,profile:read_all",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code_for_token(code):
    r = requests.post(
        TOKEN_URL,
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def refresh_access_token(token_data):
    r = requests.post(
        TOKEN_URL,
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": token_data["refresh_token"],
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def get_valid_access_token():
    token_data = load_json(TOKEN_FILE)

    code = st.query_params.get("code")

    # Wenn schon ein Token existiert, alten OAuth-Code aus der URL ignorieren
    if code and token_data is not None:
        st.query_params.clear()
        st.rerun()

    # Nur wenn noch kein Token existiert, Code eintauschen
    if code and token_data is None:
        try:
            token_data = exchange_code_for_token(code)
            save_json(TOKEN_FILE, token_data)
            st.query_params.clear()
            st.rerun()
        except requests.exceptions.HTTPError:
            st.query_params.clear()
            st.error(
                "Der Strava-Code ist abgelaufen oder wurde bereits verwendet. "
                "Bitte erneut mit Strava verbinden."
            )
            st.link_button("Erneut mit Strava verbinden", get_authorization_url())
            st.stop()

    if token_data is None:
        st.info("Bitte einmal mit Strava verbinden.")
        st.link_button("Mit Strava verbinden", get_authorization_url())
        st.stop()

    if token_data.get("expires_at", 0) < time.time() + 300:
        token_data = refresh_access_token(token_data)
        save_json(TOKEN_FILE, token_data)

    return token_data["access_token"]


# ============================================================
# CACHE / API
# ============================================================

def cache_is_valid(cache):
    if not cache:
        return False
    age = time.time() - cache.get("saved_at", 0)
    return age < CACHE_MAX_AGE_HOURS * 3600


def fetch_athlete_and_gear(access_token):
    headers = {"Authorization": f"Bearer {access_token}"}

    r = requests.get(ATHLETE_URL, headers=headers, timeout=30)
    r.raise_for_status()

    athlete = r.json()

    gear_lookup = {}

    for bike in athlete.get("bikes", []):
        gear_lookup[bike["id"]] = bike["name"]

    for shoe in athlete.get("shoes", []):
        gear_lookup[shoe["id"]] = shoe["name"]

    return athlete, gear_lookup


def fetch_activities(access_token):
    headers = {"Authorization": f"Bearer {access_token}"}

    activities = []
    page = 1

    while True:
        r = requests.get(
            ACTIVITIES_URL,
            headers=headers,
            params={"page": page, "per_page": 200},
            timeout=30,
        )
        r.raise_for_status()

        batch = r.json()

        if not batch:
            break

        activities.extend(batch)
        page += 1

    return activities


def load_strava_data(access_token, force_refresh=False):
    cache = load_json(CACHE_FILE)

    if not force_refresh and cache_is_valid(cache):
        return cache["athlete"], cache["gear_lookup"], cache["activities"], True

    athlete, gear_lookup = fetch_athlete_and_gear(access_token)
    activities = fetch_activities(access_token)

    cache = {
        "saved_at": time.time(),
        "athlete": athlete,
        "gear_lookup": gear_lookup,
        "activities": activities,
    }

    save_json(CACHE_FILE, cache)

    return athlete, gear_lookup, activities, False


# ============================================================
# STREAMLIT
# ============================================================

st.set_page_config(
    page_title="Strava Dashboard",
    layout="wide",
)

st.title("🏃‍♂️🚴 Strava Dashboard")

access_token = get_valid_access_token()

with st.sidebar:
    st.header("System")

    force_refresh = st.button("Daten neu von Strava laden")

    if st.button("Login zurücksetzen"):
        if TOKEN_FILE.exists():
            TOKEN_FILE.unlink()
        st.rerun()

    if st.button("Cache löschen"):
        if CACHE_FILE.exists():
            CACHE_FILE.unlink()
        st.rerun()

    if st.button("Einstellungen zurücksetzen"):
        if SETTINGS_FILE.exists():
            SETTINGS_FILE.unlink()
        st.rerun()


athlete, gear_lookup, activities, from_cache = load_strava_data(
    access_token,
    force_refresh=force_refresh,
)

st.caption("Daten aus Cache geladen" if from_cache else "Daten neu von Strava geladen")


# ============================================================
# DATAFRAME
# ============================================================

rows = []

for activity in activities:
    gear_id = activity.get("gear_id")
    gear_name = gear_lookup.get(gear_id, "Unknown")

    activity_type = activity.get("type", "")

    if activity_type in ["Ride", "VirtualRide", "EBikeRide", "MountainBikeRide", "GravelRide"]:
        sport_group = "Radfahren"
    elif activity_type in ["Run", "TrailRun", "VirtualRun"]:
        sport_group = "Laufen"
    else:
        sport_group = "Sonstiges"

    rows.append({
        "date": pd.to_datetime(activity.get("start_date_local")),
        "sport_group": sport_group,
        "gear_id": gear_id,
        "gear": gear_name,
        "distance_km": (activity.get("distance", 0) or 0) / 1000.0,
        "name": activity.get("name", ""),
        "type": activity_type,
        "moving_time_min": (activity.get("moving_time", 0) or 0) / 60.0,
        "elevation_m": activity.get("total_elevation_gain", 0) or 0,
    })

df = pd.DataFrame(rows)

if df.empty:
    st.error("Keine Aktivitäten gefunden.")
    st.stop()

df = df.sort_values("date")


# ============================================================
# SESSION STATE INITIALISIEREN
# ============================================================

settings = load_settings()

if "initialized" not in st.session_state:
    st.session_state.initialized = True

    st.session_state.sport_mode = settings.get("sport_mode", "Radfahren")

    min_date = df["date"].min().date()
    max_date = df["date"].max().date()

    saved_range = settings.get("date_range", [])

    if len(saved_range) == 2:
        try:
            start = pd.to_datetime(saved_range[0]).date()
            end = pd.to_datetime(saved_range[1]).date()
        except Exception:
            start, end = min_date, max_date
    else:
        start, end = min_date, max_date

    st.session_state.date_range = (
        max(start, min_date),
        min(end, max_date),
    )

    st.session_state.selected_gears = settings.get("selected_gears", [])
    st.session_state.selected_types = settings.get("selected_types", [])


# ============================================================
# SIDEBAR FILTER
# ============================================================

st.sidebar.header("Filter")

sport_mode = st.sidebar.radio(
    "Sportart",
    ["Radfahren", "Laufen", "Alle"],
    key="sport_mode",
    on_change=save_settings,
)

if sport_mode == "Alle":
    base_df = df.copy()
else:
    base_df = df[df["sport_group"] == sport_mode].copy()

available_types = sorted(base_df["type"].unique())

if not st.session_state.selected_types:
    st.session_state.selected_types = available_types

st.session_state.selected_types = [
    t for t in st.session_state.selected_types if t in available_types
] or available_types

selected_types = st.sidebar.multiselect(
    "Aktivitätstyp",
    available_types,
    key="selected_types",
    on_change=save_settings,
)

base_df = base_df[base_df["type"].isin(selected_types)].copy()

if sport_mode == "Radfahren":
    available_gears = sorted(base_df["gear"].unique())

    if not st.session_state.selected_gears:
        st.session_state.selected_gears = available_gears

    st.session_state.selected_gears = [
        g for g in st.session_state.selected_gears if g in available_gears
    ] or available_gears

    selected_gears = st.sidebar.multiselect(
        "Gear / Bike",
        available_gears,
        key="selected_gears",
        on_change=save_settings,
    )

    base_df = base_df[base_df["gear"].isin(selected_gears)].copy()

else:
    selected_gears = []


min_date = df["date"].min().date()
max_date = df["date"].max().date()

date_range = st.sidebar.date_input(
    "Zeitraum",
    min_value=min_date,
    max_value=max_date,
    key="date_range",
    on_change=save_settings,
)

filtered = base_df.copy()

if len(date_range) == 2:
    start_date, end_date = date_range

    filtered = filtered[
        (filtered["date"].dt.date >= start_date)
        & (filtered["date"].dt.date <= end_date)
    ]


# Einstellungen nach allen Widget-Änderungen sichern
save_settings()


# ============================================================
# KPIS
# ============================================================

st.subheader("📊 Übersicht")

col1, col2, col3, col4 = st.columns(4)

col1.metric("Kilometer", f"{filtered['distance_km'].sum():.1f} km")
col2.metric("Aktivitäten", len(filtered))

if sport_mode == "Radfahren":
    col3.metric("Gear", filtered["gear"].nunique())
else:
    col3.metric("Sportart", sport_mode)

col4.metric("Höhenmeter", f"{filtered['elevation_m'].sum():.0f} m")


# ============================================================
# KUMULIERTE KM
# ============================================================

st.subheader("📈 Kumulierte Kilometer")

plot_df = filtered.sort_values("date").copy()

if sport_mode == "Radfahren":
    group_col = "gear"
else:
    group_col = "type"

plot_df["cum_km"] = (
    plot_df
    .groupby(group_col)["distance_km"]
    .cumsum()
)

fig = px.line(
    plot_df,
    x="date",
    y="cum_km",
    color=group_col,
    markers=True,
    labels={
        "date": "Datum",
        "cum_km": "Kumulierte km",
        group_col: "Kategorie",
    },
)

st.plotly_chart(fig, use_container_width=True)


# ============================================================
# SUMMARY
# ============================================================

st.subheader("📋 Zusammenfassung")

summary_group = "gear" if sport_mode == "Radfahren" else "type"

summary = (
    filtered
    .groupby(summary_group, as_index=False)
    .agg(
        distance_km=("distance_km", "sum"),
        activities=("name", "count"),
        elevation_m=("elevation_m", "sum"),
        moving_time_min=("moving_time_min", "sum"),
    )
    .sort_values("distance_km", ascending=False)
)

fig_bar = px.bar(
    summary,
    x=summary_group,
    y="distance_km",
    text_auto=".1f",
)

st.plotly_chart(fig_bar, use_container_width=True)

st.dataframe(summary, use_container_width=True)


# ============================================================
# AKTIVITÄTEN
# ============================================================

st.subheader("📋 Aktivitäten")

st.dataframe(
    filtered.sort_values("date", ascending=False),
    use_container_width=True,
)