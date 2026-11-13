"""Hours of Service simulator: each FMCSA rule with round numbers (50 mph, so 50 miles = 1 hour)."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from backend.brain import hos

CT = ZoneInfo("America/Chicago")
START = datetime(2026, 11, 16, 6, 0, tzinfo=CT)  # a Monday


def hours_after_start(driver):
    return (driver.now - START).total_seconds() / 3600


def test_eight_hours_of_driving_needs_no_break():
    d = hos.drive(hos.Driver(now=START), 400)
    assert hours_after_start(d) == 8
    assert [e["status"] for e in d.log] == ["driving"]


def test_thirty_minute_break_after_eight_hours():
    d = hos.drive(hos.Driver(now=START), 500)          # 10 h of driving
    assert hours_after_start(d) == 10.5               # 8 h + 30 min break + 2 h
    assert [e["note"] for e in d.log if e["status"] == "off_duty"] == ["30-minute break"]


def test_eleven_hour_limit_forces_a_ten_hour_reset():
    d = hos.drive(hos.Driver(now=START), 700)          # 14 h of driving
    assert hours_after_start(d) == 8 + 0.5 + 3 + 10 + 3
    assert d.resets == 1


def test_dock_time_burns_the_fourteen_hour_window():
    d = hos.Driver(now=START)
    hos.on_duty(d, 5 * 60, "detention at the shipper")  # 5 h at the dock: also counts as the break
    hos.drive(d, 600)                                   # 12 h of driving
    # 8 h, 30-min break, 0.5 h until the 14-h window closes at hour 14, 10-h reset, the last 3.5 h.
    assert hours_after_start(d) == 5 + 8 + 0.5 + 0.5 + 10 + 3.5
    assert d.resets == 1


def test_thirty_minutes_on_duty_counts_as_the_break():
    d = hos.Driver(now=START)
    hos.drive(d, 350)                                   # 7 h
    hos.on_duty(d, 30, "fuel")
    hos.drive(d, 150)                                   # 3 h more: no break needed, 10 h < 11 h
    assert hours_after_start(d) == 7 + 0.5 + 3
    assert all(e["note"] != "30-minute break" for e in d.log)


def test_ten_hours_off_duty_resets_the_shift():
    d = hos.drive(hos.Driver(now=START), 550)           # 11 h driving + break: out of hours
    hos.off_duty(d, d.now + timedelta(hours=10))
    assert d.driven_shift == timedelta() and d.shift_start is None and d.resets == 1


def facility(hours=("06:00", "18:00"), dock=60):
    days = {day: {"open": hours[0], "close": hours[1]} for day in hos.WEEKDAYS[:5]}
    return {"timezone": "America/Chicago", "avg_unload_minutes": dock, "operating_hours": days}


def test_backhaul_same_day_when_driver_has_hours():
    d = hos.Driver(now=START.replace(hour=9))           # rested, empty at 09:00
    result = hos.backhaul_check(d, facility(), date(2026, 11, 16), loaded_miles=300)
    assert result["ok"] and not result["tight"]
    assert result["pickup_at"] == "11/16 09:00 CST" and result["arrive_at"] == "11/16 16:00 CST"


def test_backhaul_blocked_when_the_reset_pushes_past_closing():
    d = hos.drive(hos.Driver(now=START), 550)           # out of driving hours at 17:30
    # pickup across town needs driving, so the 10-hour reset comes first: earliest pickup is next morning
    result = hos.backhaul_check(d, facility(), date(2026, 11, 16), loaded_miles=300, deadhead_miles=15)
    assert not result["ok"]
    assert "after the pickup facility closes" in result["reasons"][0]


def test_backhaul_waits_for_the_facility_and_flags_a_tight_window():
    early = hos.backhaul_check(hos.Driver(now=START.replace(hour=4)), facility(), date(2026, 11, 16), loaded_miles=100)
    assert early["ok"] and early["pickup_at"] == "11/16 06:00 CST"   # waits for the 06:00 opening

    late = hos.backhaul_check(hos.Driver(now=START.replace(hour=16, minute=30)), facility(), date(2026, 11, 16),
                              loaded_miles=100)
    assert late["ok"] and late["tight"]                 # starts 16:30, closes 18:00: 1.5 h of slack
    assert "tight" in late["reasons"][-1]


def test_closed_on_the_weekend():
    d = hos.Driver(now=START)
    result = hos.backhaul_check(d, facility(), date(2026, 11, 21), loaded_miles=100)  # Saturday
    assert not result["ok"] and "closed" in result["reasons"][0]


def test_delivery_deadline():
    d = hos.Driver(now=START.replace(hour=9))
    result = hos.backhaul_check(d, facility(), date(2026, 11, 16), loaded_miles=300,
                                deliver_by=START.replace(hour=15))
    assert not result["ok"] and "after the required" in result["reasons"][-1]


def test_driver_after_outbound_waits_for_the_appointment():
    shipment = {
        "shipment_id": "7300001", "pickup_date": "2026-11-14", "delivery_date_target": "2026-11-16",
        "shipper_city": "Chicago", "consignee_city": "Dallas", "miles": 925,
        "stops": [
            {"stop_type": "PICKUP", "facility_id": "ORIGIN",
             "scheduled_window": {"earliest_local": "2026-11-14T08:00:00", "timezone": "America/Chicago"}},
            {"stop_type": "DELIVERY", "facility_id": "DEST",
             "scheduled_window": {"earliest_local": "2026-11-16T07:00:00", "timezone": "America/Chicago"}},
        ],
    }
    facilities = {"ORIGIN": facility(dock=45), "DEST": facility(dock=150)}
    d = hos.driver_after_outbound(shipment, facilities)
    # 925 mi = 18.5 h of driving with a reset on the way; arrives early, waits for 07:00, unloads 2.5 h.
    assert d.now == datetime(2026, 11, 16, 9, 30, tzinfo=ZoneInfo("America/Chicago"))
    assert d.driven_shift == timedelta()                # the long wait before the appointment was a reset
