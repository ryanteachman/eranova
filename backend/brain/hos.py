"""FMCSA Hours of Service (49 CFR Part 395, property-carrying drivers) as a trip simulator.

Meridian has no ELD logs, so a driver's clocks are estimated from the loads themselves: the outbound
load's pickup window, its miles at AVG_SPEED_MPH, dock time from the facility's avg_unload_minutes, and
the delivery appointment. The simulator then plays the backhaul forward and inserts the breaks and
resets the rules require.

Rules modelled:
- 30-minute break after 8 hours of driving (any non-driving time of 30+ minutes counts).
- 11 hours of driving per shift.
- 14-hour on-duty window from the first on-duty minute; dock time and waiting do not pause it.
- 10 consecutive hours off duty reset the shift (and the window).

Not modelled (documented assumptions): the 60/70-hour weekly cap and 34-hour restart (no driver
history in Meridian; every driver is assumed to have hours left in the week), sleeper-berth splits
and the adverse-conditions extension (leaving them out can only make a trip look slower, never
illegal), and the short-haul exemption. Times are timezone-aware; facility-local times use the
facility's timezone.
"""

from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

MAX_DRIVING_BEFORE_BREAK = timedelta(hours=8)
BREAK = timedelta(minutes=30)
MAX_DRIVING_PER_SHIFT = timedelta(hours=11)
ON_DUTY_WINDOW = timedelta(hours=14)
SHIFT_RESET = timedelta(hours=10)

AVG_SPEED_MPH = 50                     # door-to-door truck average, including traffic
DEFAULT_DOCK_MINUTES = 60              # when a facility has no avg_unload_minutes
DEFAULT_HOURS = ("06:00", "18:00")     # when a facility has no operating hours
DEFAULT_TZ = "America/Chicago"
LOCAL_DEADHEAD_MILES = 15              # between two facilities in the same city
TIGHT_SLACK = timedelta(hours=2)       # less than this before the pickup facility closes is "tight"
SEARCH_DAYS = 3                        # earliest_backhaul looks this many days past the empty day
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass
class Driver:
    """A driver's clocks at a moment in time. `now` is timezone-aware."""
    now: datetime
    shift_start: datetime | None = None          # first on-duty minute of the current shift
    driven_shift: timedelta = timedelta()
    driven_since_break: timedelta = timedelta()
    resets: int = 0                               # 10-hour resets taken so far
    log: list = field(default_factory=list)       # [{status, start, end, note}]


def _record(driver, status, start, note):
    driver.log.append({"status": status, "start": start, "end": driver.now, "note": note})


def _reset(driver):
    driver.shift_start = None
    driver.driven_shift = timedelta()
    driver.driven_since_break = timedelta()


def off_duty(driver, until, note="off duty"):
    """Wait off duty until `until`. 10+ hours resets the shift; 30+ minutes counts as the driving break."""
    if until <= driver.now:
        return driver
    start, gap = driver.now, until - driver.now
    driver.now = until
    if gap >= SHIFT_RESET:
        _reset(driver)
        driver.resets += 1
    elif gap >= BREAK:
        driver.driven_since_break = timedelta()
    _record(driver, "off_duty", start, note)
    return driver


def rest(driver, note="10-hour reset"):
    """Take the full 10-hour off-duty reset."""
    return off_duty(driver, driver.now + SHIFT_RESET, note)


def on_duty(driver, minutes, note="on duty"):
    """Work without driving (loading, unloading, paperwork). Starts the 14-hour window; 30+ minutes counts as a break."""
    start = driver.now
    if driver.shift_start is None:
        driver.shift_start = start
    driver.now += timedelta(minutes=minutes)
    if minutes >= BREAK.total_seconds() / 60:
        driver.driven_since_break = timedelta()
    _record(driver, "on_duty", start, note)
    return driver


def drive(driver, miles, note="driving"):
    """Drive `miles`, inserting 30-minute breaks and 10-hour resets wherever the rules require them."""
    remaining = timedelta(hours=miles / AVG_SPEED_MPH)
    while remaining > timedelta():
        if driver.shift_start is None:
            driver.shift_start = driver.now
        left_break = MAX_DRIVING_BEFORE_BREAK - driver.driven_since_break
        left_shift = MAX_DRIVING_PER_SHIFT - driver.driven_shift
        left_window = driver.shift_start + ON_DUTY_WINDOW - driver.now
        allowed = min(remaining, left_break, left_shift, left_window)
        if allowed <= timedelta():
            if left_break <= timedelta() and left_shift > timedelta() and left_window > BREAK:
                off_duty(driver, driver.now + BREAK, "30-minute break")
            else:
                rest(driver)
            continue
        start = driver.now
        driver.now += allowed
        driver.driven_shift += allowed
        driver.driven_since_break += allowed
        remaining -= allowed
        _record(driver, "driving", start, note)
    return driver


# ---------- Meridian data → times ----------

def facility_tz(facility):
    """The facility's timezone, or DEFAULT_TZ."""
    return ZoneInfo((facility or {}).get("timezone") or DEFAULT_TZ)


def local_time(text, tz):
    """'2026-11-16T07:00:00' (facility-local) → an aware datetime."""
    return datetime.fromisoformat(text).replace(tzinfo=tz)


def utc_time(text):
    """'2026-11-13T12:10:42Z' → an aware datetime."""
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def dock_minutes(facility):
    """Typical time at the dock for this facility."""
    return (facility or {}).get("avg_unload_minutes") or DEFAULT_DOCK_MINUTES


def facility_hours(facility, day):
    """(open, close) aware datetimes for this facility on `day`, or None when it is closed that day."""
    tz = facility_tz(facility)
    hours = (facility or {}).get("operating_hours")
    if hours:
        today = hours.get(WEEKDAYS[day.weekday()])
        if not today:
            return None
        open_, close = today["open"], today["close"]
    else:
        open_, close = DEFAULT_HOURS
    to_dt = lambda hhmm: datetime.combine(day, time.fromisoformat(hhmm), tz)
    return to_dt(open_), to_dt(close)


def _stop(shipment, stop_type):
    stops = [s for s in shipment.get("stops") or [] if s.get("stop_type") == stop_type]
    return stops[0] if stop_type == "PICKUP" and stops else (stops[-1] if stops else {})


def _window_start(stop, facility, fallback_date, fallback_hour=8):
    window = stop.get("scheduled_window") or {}
    tz = ZoneInfo(window.get("timezone") or facility_tz(facility).key)
    if window.get("earliest_local"):
        return local_time(window["earliest_local"], tz)
    return datetime.combine(date.fromisoformat(fallback_date), time(fallback_hour), tz)


def driver_after_outbound(shipment, facilities, miles=None):
    """Estimate the driver's clocks the moment the outbound load is unloaded (the truck is empty)."""
    pickup, delivery = _stop(shipment, "PICKUP"), _stop(shipment, "DELIVERY")
    origin = facilities.get(pickup.get("facility_id"))
    dest = facilities.get(delivery.get("facility_id"))
    miles = miles or shipment.get("miles") or 0

    driver = Driver(now=_window_start(pickup, origin, shipment["pickup_date"]))
    on_duty(driver, dock_minutes(origin), f"loading at {pickup.get('facility_id') or shipment['shipper_city']}")
    drive(driver, miles, f"outbound {shipment['shipment_id']} ({miles} mi)")
    appointment = _window_start(delivery, dest, shipment.get("delivery_date_target") or shipment["pickup_date"])
    off_duty(driver, appointment, "waiting for the delivery appointment")
    on_duty(driver, dock_minutes(dest), f"unloading at {delivery.get('facility_id') or shipment['consignee_city']}")

    # A delivered load's real departure time beats the estimate.
    if delivery.get("actual_departure"):
        off_duty(driver, utc_time(delivery["actual_departure"]), "actual departure from Meridian")
    return driver


def backhaul_check(driver, pickup_facility, pickup_day, loaded_miles, deadhead_miles=0, deliver_by=None):
    """Can this driver legally make the backhaul? Returns {ok, tight, pickup_at, arrive_at, pickup_date,
    delivery_date, slack, resets, reasons}; the *_at values are display strings, the *_date values ISO dates.

    pickup_day is the requested pickup date; the pickup must start while the pickup facility is open that day.
    """
    d = replace(driver, log=list(driver.log))
    tz = facility_tz(pickup_facility)
    fmt = lambda dt: dt.astimezone(tz).strftime("%m/%d %H:%M %Z")
    empty_at, resets_before = d.now, d.resets
    if deadhead_miles:
        drive(d, deadhead_miles, f"deadhead to pickup ({deadhead_miles} mi)")

    hours = facility_hours(pickup_facility, pickup_day)
    if hours is None:
        return {"ok": False, "tight": False, "pickup_at": None, "arrive_at": None, "slack": None,
                "pickup_date": None, "delivery_date": None, "resets": d.resets - resets_before,
                "reasons": [f"Blocked: HOS/hours: the pickup facility is closed on {pickup_day:%a %m/%d}."]}
    open_, close = hours
    off_duty(d, open_, "waiting for the pickup facility to open")
    start = d.now
    if start > close:
        return {"ok": False, "tight": False, "pickup_at": fmt(start), "arrive_at": None, "slack": None,
                "pickup_date": None, "delivery_date": None, "resets": d.resets - resets_before,
                "reasons": [f"Blocked: HOS: truck is empty {fmt(empty_at)}; the earliest legal pickup is "
                            f"{fmt(start)}, after the pickup facility closes ({fmt(close)}) on the requested day."]}

    on_duty(d, dock_minutes(pickup_facility), "loading the backhaul")
    drive(d, loaded_miles, f"backhaul ({loaded_miles} mi)")
    slack = close - start
    rests = d.resets - resets_before
    reasons = [f"HOS: truck empty {fmt(empty_at)}; earliest legal pickup {fmt(start)}; "
               f"delivery about {fmt(d.now)} ({loaded_miles} mi at {AVG_SPEED_MPH} mph, legal breaks and rests included)."]
    ok, tight = True, slack < TIGHT_SLACK
    if deliver_by and d.now > deliver_by:
        ok = False
        reasons.append(f"Blocked: HOS: the legal delivery time {fmt(d.now)} is after the required {fmt(deliver_by)}.")
    elif tight:
        reasons.append(f"HOS is tight: only {slack.total_seconds() / 3600:.1f} h before the pickup facility closes.")
    return {"ok": ok, "tight": tight, "pickup_at": fmt(start), "arrive_at": fmt(d.now),
            "pickup_date": start.astimezone(tz).date().isoformat(),
            "delivery_date": d.now.astimezone(tz).date().isoformat(),
            "slack": slack, "resets": rests, "reasons": reasons}


def earliest_backhaul(driver, pickup_facility, loaded_miles, deadhead_miles=0, search_days=SEARCH_DAYS):
    """The first day (from the day the truck empties, up to search_days later) the driver can legally make
    the backhaul; returns that day's backhaul_check result, or the last refusal when no day works."""
    first_day = driver.now.astimezone(facility_tz(pickup_facility)).date()
    result = None
    for offset in range(search_days + 1):
        result = backhaul_check(driver, pickup_facility, first_day + timedelta(days=offset),
                                loaded_miles, deadhead_miles)
        if result["ok"]:
            return result
    result["reasons"] = [f"Blocked: HOS: no legal pickup within {search_days} days of the truck emptying "
                         f"({result['reasons'][0].removeprefix('Blocked: ')})"]
    return result
