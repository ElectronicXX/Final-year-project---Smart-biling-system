from calendar import monthcalendar, monthrange
from datetime import date, datetime, timedelta

from db import db
from models import DailyCheckIn, UserDays


def month_bounds(value=None):
    value = value or date.today()
    start = value.replace(day=1)
    end = value.replace(day=monthrange(value.year, value.month)[1])
    return start, end


def sync_user_days(user_id, value=None):
    start, end = month_bounds(value)
    month = start.strftime("%B %Y")
    count = DailyCheckIn.query.filter(
        DailyCheckIn.user_id == user_id,
        DailyCheckIn.checkin_date.between(start, end),
    ).count()
    record = UserDays.query.filter_by(user_id=user_id, month=month).first()
    if record:
        record.days = count
    else:
        record = UserDays(user_id=user_id, month=month, days=count)
        db.session.add(record)
    return record


def check_in_user(user_id, checkin_date=None, source="self"):
    checkin_date = checkin_date or date.today()
    existing = DailyCheckIn.query.filter_by(
        user_id=user_id, checkin_date=checkin_date
    ).first()
    if existing:
        record = sync_user_days(user_id, checkin_date)
        return existing, record, False
    item = DailyCheckIn(
        user_id=user_id,
        checkin_date=checkin_date,
        checked_in_at=datetime.now(),
        source=source,
    )
    db.session.add(item)
    db.session.flush()
    record = sync_user_days(user_id, checkin_date)
    return item, record, True


def remove_checkin(checkin):
    user_id = checkin.user_id
    value = checkin.checkin_date
    db.session.delete(checkin)
    db.session.flush()
    return sync_user_days(user_id, value)


def user_attendance(user_id, value=None):
    value = value or date.today()
    start, end = month_bounds(value)
    is_current_month = (
        start.year == date.today().year and start.month == date.today().month
    )
    reference_day = date.today() if is_current_month else end
    records = (
        DailyCheckIn.query.filter(
            DailyCheckIn.user_id == user_id,
            DailyCheckIn.checkin_date.between(start, end),
        )
        .order_by(DailyCheckIn.checkin_date.desc())
        .all()
    )
    dates = {item.checkin_date for item in records}
    streak = 0
    cursor = reference_day
    while cursor in dates:
        streak += 1
        cursor -= timedelta(days=1)
    elapsed_days = reference_day.day
    calendar_weeks = []
    for week in monthcalendar(start.year, start.month):
        calendar_weeks.append(
            [
                {
                    "day": day,
                    "checked": date(start.year, start.month, day) in dates if day else False,
                    "today": date(start.year, start.month, day) == date.today()
                    if day
                    else False,
                }
                for day in week
            ]
        )
    return {
        "records": records,
        "dates": dates,
        "count": len(records),
        "days_in_month": end.day,
        "elapsed_days": elapsed_days,
        "attendance_rate": round((len(records) / elapsed_days) * 100, 1)
        if elapsed_days
        else 0,
        "streak": streak,
        "checked_in_today": date.today() in dates if is_current_month else False,
        "month": start.strftime("%B %Y"),
        "year": start.year,
        "month_number": start.month,
        "calendar_weeks": calendar_weeks,
    }
