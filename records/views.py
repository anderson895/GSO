from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_protect
from .models import WasteRecord, Profile, Area, GeneratedReport, ThresholdSettings, ResponseGuidelines, DeanMessage, AuditLog
from .forms import WasteForm, EditWasteForm
from datetime import date, timedelta
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from zoneinfo import ZoneInfo
from django.db.models import Sum, Count, Max
from django.http import HttpResponse
from django.db.models.functions import TruncMonth
from itertools import groupby
import calendar
from collections import defaultdict
import json


def group_records_by_area(records, report_type):
    """Group waste records per area with subtotal and overall alert level."""

    ordered = sorted(records, key=lambda r: str(r.area))

    groups = []

    for area, items in groupby(ordered, key=lambda r: str(r.area)):

        items = list(items)

        total_bags = sum(r.amount or 0 for r in items)

        alert_level, _ = get_level_action(
            total_bags,
            report_type
        )

        groups.append({
            'area': area,
            'records': items,
            'total_bags': total_bags,
            'record_count': len(items),
            'alert_level': alert_level,
        })

    return groups

##HEAD SUPERVISOR'S SETUP PAGE
def admin_exists():
    return Profile.objects.filter(role='Head Supervisor').exists()

def setup_admin(request):

    if admin_exists():
        return redirect('login')

    if request.method == 'POST':
        setup_key = request.POST['setup_key']
        employee_id = request.POST['employee_id']
        password = request.POST['password']
        confirm_password = request.POST['confirm_password']

        if setup_key != 'GSO2026HEADSUPERVISOR':
            messages.error(request, 'Invalid setup key.')
            return redirect('setup_admin')

        if password != confirm_password:
            messages.error(request, 'Passwords do not match.')
            return redirect('setup_admin')

        last_four = employee_id[-4:]
        username = f"HSV-{last_four}"

        user = User.objects.create_user(
            username=username,
            password=password
        )

        Profile.objects.create(
            user=user,
            role='Head Supervisor',
            employee_id=employee_id
        )

        messages.success(request, 'Head Supervisor account created successfully.')
        return redirect('login')

    return render(request, 'setup_admin.html')

ALERT_DESCRIPTIONS = {
    'Critical': 'The college is producing a critical amount of plastic or waste. Immediate action is encouraged.',
    'High': 'The college is producing a high volume of plastic or waste. Reduction efforts are recommended.',
    'Moderate': 'The college is producing a moderate amount of plastic or waste. Proper disposal and monitoring are advised.',
    'Low': 'The college is maintaining a low level of plastic or waste. Continue practicing proper waste management.',
}

COLOR_MAP = {
    'Critical': 'rgba(185, 28, 28, 0.95)',
    'High': 'rgba(239, 68, 68, 0.75)',
    'Moderate': 'rgba(234, 179, 8, 0.9)',
    'Low': 'rgba(16, 185, 129, 0.9)',
}

LEVEL_ORDER = {
    'Low': 0,
    'Moderate': 1,
    'High': 2,
    'Critical': 3,
}

# Colors used for the "Waste per Area" bar chart / legend (matches design reference).
GRAPH_LEVEL_COLORS = {
    'Low': '#f6c445',       # amber
    'Moderate': '#74c476',  # green
    'High': '#f39019',      # orange
    'Critical': '#e5484d',  # red
}

# Colors used by the status pills / status labels across tables and area cards.
STATUS_LEVEL_COLORS = {
    'Low': '#16a34a',       # green
    'Moderate': '#fbbf24',  # yellow
    'High': '#f87171',      # red
    'Critical': '#991b1b',  # dark red
}


def format_amount(value):
    """Format a bag count for display: 5.0 -> '5', 1000.01 -> '1,000.01'."""

    value = round(float(value), 2)

    if value == int(value):
        return f"{int(value):,}"

    return f"{value:,.2f}".rstrip("0")


def _level_ranges(reporting_period):
    """Return (level, range-text) pairs based on the selected thresholds."""

    settings = get_threshold_settings(reporting_period)

    low = settings.low_max
    mod = settings.moderate_max
    high = settings.high_max

    fmt = format_amount

    return [
        ("Low", f"0 - {fmt(low)} bags"),
        ("Moderate", f"{fmt(low + 0.01)} - {fmt(mod)} bags"),
        ("High", f"{fmt(mod + 0.01)} - {fmt(high)} bags"),
        ("Critical", f"{fmt(high + 0.01)}+ bags"),
    ]


def build_level_legend(color_map=None, reporting_period="daily"):
    """
    Return legend rows (label, range text, color)
    based on the selected reporting period.
    """

    if color_map is None:
        color_map = GRAPH_LEVEL_COLORS

    return [
        {
            "level": level,
            "range": rng,
            "color": color_map[level],
        }
        for level, rng in _level_ranges(reporting_period)
    ]


def janitor_required(view_func):
    def wrapper(request, *args, **kwargs):
        if request.user.profile.role != 'Lead Janitor':
            return redirect('waste_list')
        return view_func(request, *args, **kwargs)
    return wrapper


REPORTING_PERIOD_MAP = {
    "daily": "Today",
    "weekly": "This Week",
    "monthly": "This Month",
    "yearly": "This Year",
}


def get_threshold_settings(reporting_period):
    """Thresholds for a reporting period.

    Falls back to the daily thresholds when the caller has no period yet
    (e.g. the reports page before a report type is chosen), and creates the
    row on first use so a fresh database never 500s.
    """

    period_name = REPORTING_PERIOD_MAP.get(reporting_period, "Today")

    settings, _ = ThresholdSettings.objects.get_or_create(
        reporting_period=period_name
    )

    return settings


def get_level_action(amount, reporting_period="daily"):

    settings = get_threshold_settings(reporting_period)

    if amount <= settings.low_max:
        return "Low", ALERT_DESCRIPTIONS["Low"]

    elif amount <= settings.moderate_max:
        return "Moderate", ALERT_DESCRIPTIONS["Moderate"]

    elif amount <= settings.high_max:
        return "High", ALERT_DESCRIPTIONS["High"]

    return "Critical", ALERT_DESCRIPTIONS["Critical"]


def get_stronger_alert(first, second):
    return first if LEVEL_ORDER.get(first, 0) >= LEVEL_ORDER.get(second, 0) else second


def get_reporting_period_key(record_date, reporting_period):

    if reporting_period == "daily":
        return record_date.strftime("%A")

    elif reporting_period == "weekly":
        week_number = ((record_date.day - 1) // 7) + 1
        if week_number > 4:
            week_number = 4
        return f"Week {week_number}"

    elif reporting_period == "monthly":
        return calendar.month_name[record_date.month]

    elif reporting_period == "yearly":
        return str(record_date.year)

    return None


def get_reporting_period_labels(reporting_period, today):

    if reporting_period == "daily":

        monday = today - timedelta(days=today.weekday())

        labels = []

        for i in range(7):

            current = monday + timedelta(days=i)

            labels.append(
                current.strftime("%a (%b %d)")
            )

        return labels

    elif reporting_period == "weekly":

        last_day = calendar.monthrange(today.year, today.month)[1]

        labels = []

        for week in range(4):

            start = week * 7 + 1

            end = min(start + 6, last_day)

            labels.append(
                f"Week {week+1} ({calendar.month_abbr[today.month]} {start}-{end})"
            )

        return labels

    elif reporting_period == "monthly":

        return [
            calendar.month_abbr[m]
            for m in range(1, 13)
        ]

    elif reporting_period == "yearly":

        return [str(today.year)]

    return []


def aggregate_records(records, reporting_period):

    grouped = defaultdict(float)

    for record in records:

        key = get_reporting_period_key(
            record.date,
            reporting_period
        )

        grouped[key] += record.amount or 0

    today = date.today()

    totals = []

    if reporting_period == "daily":

        keys = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ]

    elif reporting_period == "weekly":

        keys = [
            "Week 1",
            "Week 2",
            "Week 3",
            "Week 4",
        ]

    elif reporting_period == "monthly":

        keys = [
            calendar.month_name[m]
            for m in range(1, 13)
        ]

    elif reporting_period == "yearly":

        keys = [str(today.year)]

    else:

        keys = []

    labels = get_reporting_period_labels(
        reporting_period,
        today
    )

    for key in keys:
        totals.append(
            grouped.get(key, 0)
        )

    return labels, totals


MANILA_TZ = ZoneInfo('Asia/Manila')


def format_submitted_at(record):
    """Submission date and time of a waste record, in Philippine time."""

    submitted_at = record.submitted_at

    if not submitted_at:
        return 'Unknown Date', 'Unknown Time'

    submitted_at = timezone.localtime(submitted_at, MANILA_TZ)

    return (
        submitted_at.strftime('%b %d, %Y'),
        submitted_at.strftime('%I:%M %p').lstrip('0'),
    )


def describe_waste_record(record):
    """One-line summary of a waste record, used as audit log details."""

    bag_label = 'Bag' if record.amount == 1 else 'Bags'

    photo_note = (
        'Photo attached'
        if record.photo
        else 'No photo attached'
    )

    return (
        f"{record.waste_type} · "
        f"{record.amount} {bag_label} Total Submitted · "
        f"{photo_note}"
    )


def build_audit_entries(actions):
    """Audit log rows for the given actions, stamped with Philippine time."""

    audit_entries = []

    logs = AuditLog.objects.filter(
        action__in=actions
    ).select_related('performed_by')

    for log in logs:
        log.displayed_at = timezone.localtime(
            log.created_at,
            MANILA_TZ
        )

        log.displayed_at_formatted = log.displayed_at.strftime(
            "%b %d, %Y %I:%M %p"
        )

        audit_entries.append(log)

    return audit_entries


@login_required
@csrf_protect
def waste_list(request):
    form = WasteForm()

    # Read filter selections from query params so both roles can use them
    selected_area = request.GET.get('area', 'All')
    selected_type = request.GET.get('type', 'All')
    type_choices = [
        choice[0]
        for choice in WasteRecord.WASTE_TYPE_CHOICES
    ]

    if request.method == 'POST':
        if request.user.profile.role != 'Lead Janitor':
            return redirect('waste_list')

        form = WasteForm(
            request.POST,
            request.FILES
        )

        if form.is_valid():
            record = form.save(commit=False)
            record.user = request.user
            record.alert_level, _ = get_level_action(
                record.amount,
                "daily"
            )
            record.save()

            AuditLog.objects.create(
                performed_by=request.user,
                action='Submitted Waste Record',
                target=record.area.area_name,
                details=describe_waste_record(record),
                waste_record=record,
                waste_record_id_snapshot=f'WR-{record.id:03d}',
            )
            return redirect('waste_list')

    if request.user.profile.role == 'Lead Janitor':
        records = WasteRecord.objects.filter(
            user=request.user
        ).order_by('-submitted_at')

        if selected_area != 'All':
            records = records.filter(
                area__area_name=selected_area
            )

        if selected_type != 'All':
            records = records.filter(
                waste_type=selected_type
            )

    else:
        records = WasteRecord.objects.all().order_by(
            '-submitted_at'
        )

        if selected_area != 'All':
            records = records.filter(
                area__area_name=selected_area
            )

        if selected_type != 'All':
            records = records.filter(
                waste_type=selected_type
            )

    total_records = records.count()

    total_waste_all = records.aggregate(
        total=Sum('amount')
    )['total'] or 0

    # Calculate month-over-month change
    today = date.today()
    current_month_start = today.replace(day=1)
    last_month_end = current_month_start - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)

    # Get current month's total
    if request.user.profile.role == 'Lead Janitor':
        current_query = WasteRecord.objects.filter(
            user=request.user,
            date__gte=current_month_start,
            date__lte=today
        )

        if selected_area != 'All':
            current_query = current_query.filter(
                area__area_name=selected_area
            )

        if selected_type != 'All':
            current_query = current_query.filter(
                waste_type=selected_type
            )

        current_month_total = current_query.aggregate(
            total=Sum('amount')
        )['total'] or 0

        last_query = WasteRecord.objects.filter(
            user=request.user,
            date__gte=last_month_start,
            date__lt=current_month_start
        )

        if selected_area != 'All':
            last_query = last_query.filter(
                area__area_name=selected_area
            )

        if selected_type != 'All':
            last_query = last_query.filter(
                waste_type=selected_type
            )

        last_month_total = last_query.aggregate(
            total=Sum('amount')
        )['total'] or 0

    else:
        current_query = WasteRecord.objects.filter(
            date__gte=current_month_start,
            date__lte=today
        )

        if selected_area != 'All':
            current_query = current_query.filter(
                area__area_name=selected_area
            )

        if selected_type != 'All':
            current_query = current_query.filter(
                waste_type=selected_type
            )

        current_month_total = current_query.aggregate(
            total=Sum('amount')
        )['total'] or 0

        last_query = WasteRecord.objects.filter(
            date__gte=last_month_start,
            date__lt=current_month_start
        )

        if selected_area != 'All':
            last_query = last_query.filter(
                area__area_name=selected_area
            )

        if selected_type != 'All':
            last_query = last_query.filter(
                waste_type=selected_type
            )

        last_month_total = last_query.aggregate(
            total=Sum('amount')
        )['total'] or 0

    # Calculate percentage change
    has_previous_data = last_query.exists()

    if not has_previous_data:
        percentage_change = None
        change_status = 'No previous data'
        is_increased = False
        change_indicator = 'neutral'
        change_display = 'No previous data'

    elif current_month_total == last_month_total:
        percentage_change = 0
        change_status = 'No Change'
        is_increased = False
        change_indicator = 'neutral'
        change_display = '0.0%'

    elif current_month_total > last_month_total:
        percentage_change = (
            (current_month_total - last_month_total)
            / last_month_total
        ) * 100

        change_status = 'Increased'
        is_increased = True
        change_indicator = 'negative'
        change_display = f'{abs(percentage_change):.1f}%'

    else:
        percentage_change = (
            (last_month_total - current_month_total)
            / last_month_total
        ) * 100

        change_status = 'Decreased'
        is_increased = False
        change_indicator = 'positive'
        change_display = f'{abs(percentage_change):.1f}%'

    # Keep every WasteRecord as an individual submission.
    # Do NOT group records by user, area, date, or time.
    data = []

    for r in records:
        level, action = get_level_action(
            r.amount,
            "daily",
        )

        data.append({
            'id': r.id,
            'waste_record_id': f'WR-{r.id:03d}',
            'area': r.area,
            'date': r.date,
            'time': r.time,
            'amount': r.amount,
            'waste_type': r.waste_type,
            'alert_level': level,
            'action': action,
            'photo_url': r.photo.url if r.photo else None,
            'janitor': (
                r.user.username
                if r.user
                else 'Unknown'
            ),
            'submitted_at': r.submitted_at,
            'coordinator_rating': r.coordinator_rating,
            'coordinator_comment': r.coordinator_comment,
            'bags_submitted': r.amount,
        })

    threshold = get_threshold_settings("daily")

    context = {
        'form': form,
        'data': data,
        'total_records': total_records,
        'total_waste_all': total_waste_all,
        'percentage_change': (
            abs(percentage_change)
            if percentage_change is not None
            else None
        ),
        'is_increased': is_increased,
        'change_status': change_status,
        'change_indicator': change_indicator,
        'change_display': change_display,
        'selected_type': selected_type,
        'area_choices': Area.objects.values_list(
            'area_name',
            flat=True
        ),
        'threshold': threshold,
        'level_legend': build_level_legend(
            STATUS_LEVEL_COLORS,
            "daily",
        ),
    }

    if request.user.profile.role in (
        'Supervisor',
        'Lead Janitor'
    ):
        context['selected_area'] = selected_area
        context['type_choices'] = type_choices
        context['selected_type'] = selected_type

    return render(
        request,
        'waste_list.html',
        context
    )


@login_required
@csrf_protect
@janitor_required
def edit_record(request, pk):
    record = get_object_or_404(
        WasteRecord,
        id=pk,
        user=request.user
    )

    if request.method == 'POST':
        # Capture the original values before the form changes the record.
        original_area = record.area.area_name
        original_waste_type = record.waste_type
        original_amount = record.amount
        original_date = record.date
        original_time = record.time
        original_photo = record.photo.name if record.photo else None

        form = EditWasteForm(
            request.POST,
            request.FILES,
            instance=record
        )

        if form.is_valid():
            edited_record = form.save(commit=False)

            changes = []

            # Area
            new_area = edited_record.area.area_name

            if original_area != new_area:
                changes.append(
                    f"Changed area from {original_area} to {new_area}"
                )

            # Waste type
            if original_waste_type != edited_record.waste_type:
                changes.append(
                    "Changed waste type from "
                    f"{original_waste_type} to "
                    f"{edited_record.waste_type}"
                )

            # Amount
            if original_amount != edited_record.amount:
                changes.append(
                    "Changed waste amount from "
                    f"{original_amount} bags to "
                    f"{edited_record.amount} bags"
                )

            # Date
            if original_date != edited_record.date:
                changes.append(
                    "Changed date from "
                    f"{original_date.strftime('%B %d, %Y')} to "
                    f"{edited_record.date.strftime('%B %d, %Y')}"
                )

            # Time
            if original_time != edited_record.time:
                old_time = (
                    original_time.strftime('%I:%M %p')
                    if original_time
                    else 'No time'
                )

                new_time = (
                    edited_record.time.strftime('%I:%M %p')
                    if edited_record.time
                    else 'No time'
                )

                changes.append(
                    f"Changed time from {old_time} to {new_time}"
                )

            # Handle the photo clear checkbox.
            photo_cleared = (
                form.cleaned_data.get('photo') is False
            )

            if photo_cleared:
                if edited_record.photo:
                    edited_record.photo.delete(save=False)

                edited_record.photo = None

            edited_record.alert_level, _ = get_level_action(
                edited_record.amount,
                "daily"
            )

            # Determine what happened to the photo.
            new_photo = (
                edited_record.photo.name
                if edited_record.photo
                else None
            )

            if photo_cleared and original_photo:
                changes.append("Removed the photo")

            elif original_photo is None and new_photo:
                changes.append("Added a photo")

            elif (
                original_photo
                and new_photo
                and original_photo != new_photo
            ):
                changes.append("Replaced the photo")

            edited_record.save()

            # Only create an audit entry when an actual change occurred.
            if changes:
                AuditLog.objects.create(
                    performed_by=request.user,
                    action='Edited Waste Record',
                    target=edited_record.area.area_name,
                    details='; '.join(changes),
                    waste_record=edited_record,
                    waste_record_id_snapshot=f'WR-{edited_record.id:03d}',
                )

            return redirect('waste_list')

    else:
        form = EditWasteForm(instance=record)

    return render(
        request,
        'edit.html',
        {'form': form}
    )


@login_required
@janitor_required
def delete_record(request, pk):
    record = get_object_or_404(
        WasteRecord,
        id=pk,
        user=request.user
    )

    # Capture the latest version of the record
    # immediately before deletion.
    area_name = record.area.area_name
    details = describe_waste_record(record)

    AuditLog.objects.create(
        performed_by=request.user,
        action='Deleted Waste Record',
        target=area_name,
        details=details,
        waste_record=record,
        waste_record_id_snapshot=f'WR-{record.id:03d}',
    )

    record.delete()

    return redirect('waste_list')

@login_required
def waste_graphs(request):

    if request.user.profile.role != 'Supervisor':
        return redirect('waste_list')

    period = request.GET.get('period', 'yearly')
    category = request.GET.get('category', 'both')
    line_period = request.GET.get('line_period', 'yearly')
    selected_area = request.GET.get('area', 'All')

    today = date.today()

    # PERIOD FILTER
    if period == "daily":
        start_date = today
        period_title = "Daily"

    elif period == "weekly":
        start_date = today - timedelta(days=6)
        period_title = "Weekly"

    elif period == "monthly":
        start_date = today - timedelta(days=29)
        period_title = "Monthly"

    elif period == "yearly":
        start_date = today - timedelta(days=364)
        period_title = "Yearly"

    waste_qs = WasteRecord.objects.all()

    # FILTER BY AREA
    if selected_area != 'All':
        waste_qs = waste_qs.filter(
            area__area_name=selected_area
        )

    # FILTER BY CATEGORY
    if category in [
        'Waste With Plastic',
        'Plastic Only',
        'Waste Without Plastic'
    ]:
        waste_qs = waste_qs.filter(
            waste_type=category
        )

    # FILTER BY DATE
    if start_date:
        waste_qs = waste_qs.filter(
            date__gte=start_date,
            date__lte=today
        )

    records = waste_qs

    # BAR GRAPH
    area_totals = {}

    for record in records:

        area_name = record.area.area_name

        if area_name not in area_totals:
            area_totals[area_name] = {
                'total': 0,
                'level': 'Low'
            }

        area_totals[area_name]['total'] += record.amount

        area_totals[area_name]['level'] = get_stronger_alert(
            area_totals[area_name]['level'],
            record.alert_level
        )

    labels = sorted(area_totals.keys())

    totals = [
        area_totals[label]['total']
        for label in labels
    ]

    bar_colors = []

    for label in labels:

        total = area_totals[label]["total"]

        threshold_period = period if period != "all" else "yearly"

        level, _ = get_level_action(
            total,
            threshold_period,
        )

        bar_colors.append(
            GRAPH_LEVEL_COLORS[level]
        )

    # SUMMARY
    period_total = sum(totals)

    all_time_qs = WasteRecord.objects.all()

    if selected_area != 'All':
        all_time_qs = all_time_qs.filter(
            area__area_name=selected_area
        )

    # FILTER BY CATEGORY
    if category in [
        'Waste With Plastic',
        'Plastic Only',
        'Waste Without Plastic'
    ]:
        all_time_qs = all_time_qs.filter(
            waste_type=category
        )

    # FILTER BY DATE (same as period)
    if start_date:
        all_time_qs = all_time_qs.filter(
            date__gte=start_date,
            date__lte=today
        )

    all_time_total = all_time_qs.aggregate(
        total=Sum('amount')
    )['total'] or 0

    days = (
        (today - start_date).days + 1
        if start_date else 1
    )

    average_daily = period_total / max(days, 1)

    if totals:
        highest_building = labels[totals.index(max(totals))]
        highest_building_value = max(totals)
    else:
        highest_building = 'N/A'
        highest_building_value = 0

    # CRITICAL KPI
    # Count areas that are Critical based on their
    # aggregated waste total for the selected
    # period, category, and area filter.
    critical_count = 0

    threshold_period = period if period != "all" else "yearly"

    for area_name, area_data in area_totals.items():

        level, _ = get_level_action(
            area_data['total'],
            threshold_period,
        )

        if level == 'Critical':
            critical_count += 1

    # LINE GRAPH
    line_qs = WasteRecord.objects.all()

    # Filter by area
    if selected_area != "All":
        line_qs = line_qs.filter(
            area__area_name=selected_area
        )

    # Filter by category
    if category in [
        "Waste With Plastic",
        "Plastic Only",
        "Waste Without Plastic",
    ]:
        line_qs = line_qs.filter(
            waste_type=category
        )

    line_labels, line_data = aggregate_records(
        line_qs,
        line_period
    )

    line_title = {
        "daily": "Daily",
        "weekly": "Weekly",
        "monthly": "Monthly",
        "yearly": "Yearly",
    }.get(line_period, "Yearly")

    import json
    from .models import Area

    area_choices = Area.objects.values_list(
        'area_name',
        flat=True
    )

    return render(request, 'graphs.html', {
        'labels': json.dumps(labels),
        'totals': json.dumps(totals),
        'bar_colors': json.dumps(bar_colors),
        'has_area_data': any(totals),
        'has_trend_data': any(line_data),
        'period': period,
        'period_title': period_title,
        'period_total': period_total,
        'all_time_total': all_time_total,
        'average_daily': average_daily,
        'highest_building': highest_building,
        'highest_building_value': highest_building_value,
        'critical_count': critical_count,
        'start_date': start_date,
        'end_date': today,
        'category': category,
        'line_period': line_period,
        'line_title': line_title,
        'line_labels': json.dumps(line_labels),
        'line_data': json.dumps(line_data),
        'area_choices': area_choices,
        'selected_area': selected_area,
        'level_legend': build_level_legend(
            GRAPH_LEVEL_COLORS,
            period,
        ),
    })

@login_required
def building_status(request):
    if request.user.profile.role != 'Supervisor':
        return redirect('waste_list')

    if request.method == 'POST':
        selected_area = request.POST.get(
            'current_area',
            request.GET.get('area', 'All')
        )
        category = request.POST.get(
            'current_category',
            request.GET.get('category', 'both')
        )
        period = request.POST.get(
            'current_period',
            request.GET.get('period', 'daily')
        )
    else:
        selected_area = request.GET.get('area', 'All')
        category = request.GET.get('category', 'both')
        period = request.GET.get('period', 'daily')

    today = date.today()

    if period == 'daily':
        start_date = today
        period_title = 'Daily'
    elif period == 'weekly':
        start_date = today - timedelta(days=6)
        period_title = 'Weekly'
    elif period == 'monthly':
        start_date = today - timedelta(days=29)
        period_title = 'Monthly'
    elif period == 'yearly':
        start_date = today - timedelta(days=364)
        period_title = 'Yearly'
    else:
        start_date = today
        period_title = 'Daily'

    area_choices = Area.objects.values_list(
        'area_name',
        flat=True
    )

    if request.method == 'POST':
        report_id = request.POST.get('report_id')

        if report_id:
            report = get_object_or_404(
                WasteRecord,
                id=report_id
            )

            # Store the previous feedback before changing it
            previous_rating = report.coordinator_rating
            previous_comment = report.coordinator_comment or ''

            # Get the new feedback from the form
            new_comment = request.POST.get(
                'coordinator_comment',
                ''
            ).strip()

            rating = request.POST.get('coordinator_rating')

            try:
                new_rating = int(rating) if rating else None
            except (TypeError, ValueError):
                new_rating = None

            # Check whether anything actually changed
            feedback_changed = (
                previous_rating != new_rating
                or previous_comment != new_comment
            )

            # Save the new feedback
            report.coordinator_comment = new_comment
            report.coordinator_rating = new_rating
            report.save()

            # Create an audit log only when the feedback actually changed
            if feedback_changed:
                if previous_rating is None and not previous_comment:
                    action = 'Wrote Waste Record Feedback'
                else:
                    action = 'Edited Waste Record Feedback'

                rating_display = (
                    str(new_rating)
                    if new_rating is not None
                    else 'N/A'
                )

                comment_display = (
                    new_comment
                    if new_comment
                    else 'No feedback provided'
                )

                target = (
                    f"{report.user.username}"
                    if report.user
                    else 'TL Unknown'
                )

                area_name = (
                    report.area.area_name
                    if report.area
                    else 'Unknown Area'
                )

                submitted_date, submitted_time = format_submitted_at(report)

                details = (
                    f"{area_name} · "
                    f"{report.waste_type} · "
                    f"{report.amount} bags · "
                    f"{submitted_date} · "
                    f"{submitted_time}"
                )

                feedback = (
                    f"{rating_display} - {comment_display}"
                )

                AuditLog.objects.create(
                    performed_by=request.user,
                    action=action,
                    target=target,
                    details=details,
                    content=feedback,
                )

            return redirect(
                f"{request.path}?area={selected_area}"
                f"&category={category}&period={period}"
            )

    reports = WasteRecord.objects.all().order_by('-submitted_at')

    if selected_area != 'All':
        reports = reports.filter(
            area__area_name=selected_area
        )

    if category in [
        'Waste With Plastic',
        'Plastic Only',
        'Waste Without Plastic'
    ]:
        reports = reports.filter(
            waste_type=category
        )

    if start_date is not None:
        reports = reports.filter(
            date__gte=start_date,
            date__lte=today
        )

    report_data = []

    for report in reports:
        level, _ = get_level_action(
            report.amount,
            period,
        )

        report_data.append({
            'id': report.id,
            'area': report.area,
            'waste_type': report.waste_type,
            'alert_level': level,
            'amount': report.amount,
            'photo_url': report.photo.url if report.photo else None,
            'janitor': report.user.username if report.user else 'Unknown',
            'date': report.date,
            'time': report.time,
            'submitted_at': report.submitted_at,
            'coordinator_comment': report.coordinator_comment,
            'coordinator_rating': report.coordinator_rating,
        })

    selected_total = reports.aggregate(
        total=Sum('amount')
    )['total'] or 0

    selected_count = reports.count()
    high_count = reports.filter(
        alert_level='High'
    ).count()

    critical_count = reports.filter(
        alert_level='Critical'
    ).count()

    area_statuses = []
    base_totals = WasteRecord.objects.all()

    if category in [
        'Waste With Plastic',
        'Plastic Only',
        'Waste Without Plastic'
    ]:
        base_totals = base_totals.filter(
            waste_type=category
        )

    if start_date is not None:
        base_totals = base_totals.filter(
            date__gte=start_date,
            date__lte=today
        )

    totals_by_area = {}

    for row in base_totals:
        area_name = row.area.area_name

        if area_name not in totals_by_area:
            totals_by_area[area_name] = {
                'total': 0,
            }

        totals_by_area[area_name]['total'] += row.amount

    for area in area_choices:
        total = totals_by_area.get(
            area,
            {}
        ).get('total', 0)

        level, message = get_level_action(
            total,
            period,
        )

        area_statuses.append({
            'area': area,
            'total': total,
            'status': level,
            'message': message,
        })

    if selected_area != 'All':
        area_statuses = [
            status
            for status in area_statuses
            if status['area'] == selected_area
        ]

    threshold, created = ThresholdSettings.objects.get_or_create(
        id=1
    )

    guidelines, created = ResponseGuidelines.objects.get_or_create(
        id=1
    )

    return render(request, 'building_status.html', {
        'area_choices': area_choices,
        'selected_area': selected_area,
        'category': category,
        'period': period,
        'period_title': period_title,
        'report_data': report_data,
        'selected_total': selected_total,
        'selected_count': selected_count,
        'high_count': high_count,
        'critical_count': critical_count,
        'area_statuses': area_statuses,
        'threshold': threshold,
        'guidelines': guidelines,
        'level_legend': build_level_legend(
            STATUS_LEVEL_COLORS,
            period,
        ),
    })


@login_required
def audit_log(request):
    """Head Supervisor's view of what the Supervisors have been doing."""

    if request.user.profile.role != 'Head Supervisor':
        return redirect('waste_list')

    return render(request, 'audit_log.html', {
        'audit_entries': build_audit_entries(AuditLog.SUPERVISOR_ACTIONS),
        'tracked_role': 'Supervisor',
        'target_label': 'Target',
        'show_content': True,
    })

@login_required
def spv_audit_log(request):
    if request.user.profile.role != 'Supervisor':
        return redirect('waste_list')

    manila_tz = ZoneInfo('Asia/Manila')

    audit_entries = (
        AuditLog.objects
        .filter(
            action__in=AuditLog.JANITOR_ACTIONS
        )
        .select_related(
            'performed_by',
            'waste_record'
        )
    )

    for log in audit_entries:
        log.displayed_at = timezone.localtime(
            log.created_at,
            manila_tz
        )

        log.displayed_at_formatted = log.displayed_at.strftime(
            "%b %d, %Y %I:%M %p"
        )

        if log.waste_record_id_snapshot:
            log.waste_record_display = (
                log.waste_record_id_snapshot
            )

        elif log.waste_record:
            # Fallback for audit entries created before
            # the permanent ID snapshot was added.
            log.waste_record_display = (
                f"WR-{log.waste_record.id:03d}"
            )

        elif log.action == 'Deleted Waste Record':
            log.waste_record_display = "Record Deleted"

        else:
            # Older audit entries may not have a linked
            # WasteRecord because the relationship was added later.
            log.waste_record_display = "Unavailable"

    return render(
        request,
        'janitor_audit_log.html',
        {
            'audit_entries': audit_entries,
        }
    )

@csrf_protect
def login_view(request):
    if not admin_exists():
        return redirect('setup_admin')

    if request.method == 'POST':
        user_id = request.POST.get('user_id')
        password = request.POST.get('password')

        if not User.objects.filter(username=user_id).exists():
            messages.error(request, "User ID doesn't match credentials")
            return redirect('login')

        user = authenticate(request, username=user_id, password=password)

        if user is not None:
            login(request, user)

            role = user.profile.role

            if role == 'Head Supervisor':
                return redirect('admin_dashboard')
            else:
                return redirect('waste_list')

        else:
            messages.error(request, 'Wrong password')

    return render(request, 'login.html')


@login_required
@csrf_protect
def edit_profile(request):
    user = request.user
    profile = user.profile

    if request.method == 'POST':

        if request.POST.get('delete_account') == 'yes':
            user.delete()
            if admin_exists():
                return redirect('login')
            return redirect('setup_admin')

        # Handle password change
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')

        if new_password:
            if new_password != confirm_password:
                messages.error(request, 'Passwords do not match.')
                return redirect('edit_profile')
            if len(new_password) < 6:
                messages.error(request, 'Password must be at least 6 characters.')
                return redirect('edit_profile')
            user.set_password(new_password)
            user.save()
            messages.success(request, 'Password changed successfully. Please log in again.')
            return redirect('login')

        messages.success(request, 'Profile updated successfully.')

        if profile.role == 'Head Supervisor':
            return redirect('admin_dashboard')

        return redirect('waste_list')

    return render(request, 'profile.html', {'profile': profile})


def college_waste_summary(area_name, period='7days'):
    """Waste summary + current level for a college/area, used by the
    Message College Dean page. `period` selects the timeframe:
    '7days' (last 7 days) or 'month' (last 30 days)."""

    today = date.today()

    if period == "month":
        days = 30
        period_label = "Last 30 Days"
        reporting_period = "monthly"
    else:
        period = "7days"
        days = 7
        period_label = "Last 7 Days"
        reporting_period = "weekly"

    start = today - timedelta(days=days - 1)

    qs = WasteRecord.objects.filter(
        area__area_name=area_name,
        date__gte=start,
        date__lte=today,
    )

    reports_submitted = qs.count()

    period_total = qs.aggregate(
        total=Sum('amount')
    )['total'] or 0

    average_daily = period_total / days

    # Classify each day's total into an alert level.
    day_totals = {}

    for record in qs:
        day_totals[record.date] = (
            day_totals.get(record.date, 0) + record.amount
        )

    critical_days = high_days = moderate_days = low_days = 0

    for total in day_totals.values():
        level, _ = get_level_action(
            total,
            reporting_period
        )

        if level == 'Critical':
            critical_days += 1
        elif level == 'High':
            high_days += 1
        elif level == 'Moderate':
            moderate_days += 1
        else:
            low_days += 1

    # The current level is based on the TOTAL waste
    # accumulated during the selected monitoring period.
    current_level, current_desc = get_level_action(
        period_total,
        reporting_period
    )

    return {
        'reports_submitted': reports_submitted,
        'average_daily': round(average_daily, 2),
        'critical_days': critical_days,
        'high_days': high_days,
        'moderate_days': moderate_days,
        'low_days': low_days,
        'current_level': current_level,
        'current_desc': current_desc,
        'period': period,
        'period_label': period_label,
    }


@login_required
@csrf_protect
def message_dean(request):
    """Coordinator (Supervisor) sends an advisory message to a college Dean."""
    if request.user.profile.role != 'Supervisor':
        return redirect('waste_list')

    area_choices = list(Area.objects.values_list('area_name', flat=True))
    selected_area = request.GET.get('area') or (area_choices[0] if area_choices else '')
    period = request.GET.get('period', '7days')

    if request.method == 'POST':
        selected_area = request.POST.get('area', selected_area)
        period = request.POST.get('period', period)
        subject = request.POST.get('subject', '').strip()
        body = request.POST.get('body', '').strip()
        area = Area.objects.filter(area_name=selected_area).first()

        if area and subject and body:
            summary = college_waste_summary(selected_area, period)

            DeanMessage.objects.create(
                sender=request.user,
                area=area,
                subject=subject,
                body=body,
                alert_level=summary['current_level'],
            )

            AuditLog.objects.create(
                performed_by=request.user,
                action='Sent Advisory Message',
                target=area.area_name,
                details=(
                    f"{area.area_name} · "
                    f"{summary['period_label']} · "
                    f"{summary['average_daily']} bags/day · "
                    f"{summary['current_level']} Waste Level"
                ),
                content=subject,
            )

            messages.success(
                request,
                f'Message sent to the Dean of {selected_area}.'
            )

            return redirect(
                f"{request.path}?area={selected_area}&period={period}"
            )

        messages.error(
            request,
            'Please complete all fields before sending.'
        )

    summary = college_waste_summary(
        selected_area,
        period
    ) if selected_area else None

    sent_messages = DeanMessage.objects.filter(
        sender=request.user
    )[:10]

    default_subject = (
        f"Urgent: {summary['current_level']} Waste Level in {selected_area}"
        if summary else ''
    )

    default_body = (
        f"Good day, Dean.\n\n"
        f"Based on the waste summary for the {summary['period_label'].lower()}, "
        f"the waste level in {selected_area} is currently "
        f"{summary['current_level'].upper()}, with an average daily waste of "
        f"{summary['average_daily']} bags.\n"
        f"Immediate action is necessary to address the increasing waste "
        f"accumulation in your area.\n\n"
        f"Please advise your staff to prioritize waste collection and proper disposal.\n\n"
        f"Thank you."
        if summary else ''
    )

    return render(request, 'message_college_dean.html', {
        'area_choices': area_choices,
        'selected_area': selected_area,
        'period': period,
        'summary': summary,
        'sent_messages': sent_messages,
        'default_subject': default_subject,
        'default_body': default_body,
    })


@csrf_protect
def logout_view(request):
    logout(request)
    return redirect('login')


@login_required
def admin_dashboard(request):
    if request.user.profile.role != 'Head Supervisor':
        return redirect('waste_list')

    total_users = User.objects.count()

    total_records = WasteRecord.objects.count()

    total_waste = WasteRecord.objects.aggregate(
        total=Sum('amount')
    )['total'] or 0

    total_areas = Area.objects.count()

    trend_period = request.GET.get('trend_period', 'daily')
    trend_category = request.GET.get('trend_category', 'Waste With Plastic')
    today = date.today()
    graph_qs = WasteRecord.objects.all()

    # CATEGORY FILTER
    if trend_category in [
        'Waste With Plastic',
        'Plastic Only',
        'Waste Without Plastic'
    ]:
        graph_qs = graph_qs.filter(
            waste_type=trend_category
        )

    # PERIOD FILTER
    if trend_period == "daily":
        start_date = today - timedelta(days=today.weekday())
        end_date = start_date + timedelta(days=6)

    elif trend_period == "weekly":
        start_date = date(today.year, today.month, 1)
        last_day = calendar.monthrange(today.year, today.month)[1]
        end_date = date(today.year, today.month, last_day)

    elif trend_period == "monthly":
        start_date = date(today.year, 1, 1)
        end_date = date(today.year, 12, 31)

    elif trend_period == "yearly":
        start_date = date(today.year, 1, 1)
        end_date = today

    else:
        start_date = today - timedelta(days=today.weekday())
        end_date = start_date + timedelta(days=6)

    graph_qs = graph_qs.filter(
        date__gte=start_date,
        date__lte=end_date
    )

    graph_labels, graph_values = aggregate_records(
        graph_qs,
        trend_period
    )

    graph_labels = json.dumps(graph_labels)
    graph_values = json.dumps(graph_values)

    context = {
        'total_users': total_users,
        'total_records': total_records,
        'total_waste': total_waste,
        'total_areas': total_areas,

        'trend_period': trend_period,
        'trend_category': trend_category,

        'graph_labels': graph_labels,
        'graph_values': graph_values,
    }

    return render(request, 'admin_dashboard.html', context)


@login_required
def area_list(request):

    areas = Area.objects.all()

    return render(request, 'admin_area_list.html', {
        'areas': areas
    })


@login_required
def add_area(request):

    if request.method == 'POST':

        reactivate_area = request.POST.get(
            'reactivate_area'
        )

        if reactivate_area:

            area = Area.objects.get(
                id=reactivate_area
            )

            area.status = 'Active'

            area.save()

            return redirect('area_list')

        area_name = request.POST.get('area_name')

        force_create = request.POST.get(
            'force_create'
        )
        
        similar_areas = []

        new_first_word = area_name.lower().split()[0]

        for area in Area.objects.all():

            existing_first_word = (
                area.area_name.lower().split()[0]
            )

            if new_first_word == existing_first_word:

                similar_areas.append(area)

        existing_area = Area.objects.filter(
            area_name__iexact=area_name
        ).first()

        if existing_area:

            if existing_area:
                if existing_area.status == 'Inactive':

                    return render(
                        request,
                        'admin_add_area.html',
                        {
                            'inactive_area': existing_area
                        }
                    )

                return render(
                    request,
                    'admin_add_area.html',
                    {
                        'error':
                        f'"{area_name}" is already registered.'
                    }
                )

            return render(
                request,
                'admin_add_area.html',
                {
                    'error':
                    f'"{area_name}" is already registered.'
                }
            )
        
        if similar_areas and force_create != 'yes':

            inactive_similar_areas = [
                area
                for area in similar_areas
                if area.status == 'Inactive'
            ]

            if inactive_similar_areas:

                return render(
                    request,
                    'admin_add_area.html',
                    {
                        'inactive_similar_areas':
                        inactive_similar_areas,

                        'new_area_name':
                        area_name,
                    }
                )

            return render(
                request,
                'admin_add_area.html',
                {
                    'similar_areas':
                    similar_areas,

                    'new_area_name':
                    area_name,
                }
            )


        Area.objects.create(
            area_name=area_name
        )

        return redirect('area_list')

    return render(request, 'admin_add_area.html')


@login_required
def edit_area(request, area_id):

    area = get_object_or_404(Area, id=area_id)

    if request.method == 'POST':
        area.area_name = request.POST.get('area_name')
        area.status = request.POST.get('status')
        area.save()

        return redirect('area_list')

    return render(request, 'admin_edit_area.html', {
        'area': area
    })


@login_required
def update_area_status(request, area_id):

    if request.method == 'POST':

        area = get_object_or_404(
            Area,
            id=area_id
        )

        area.status = request.POST.get(
            'status'
        )

        area.save()

    return redirect('area_list')


@login_required
def delete_area(request, area_id):

    area = get_object_or_404(
        Area,
        id=area_id
    )

    area.delete()

    return redirect('area_list')


@login_required
def user_list(request):

    users = Profile.objects.exclude(role='Head Supervisor')

    return render(request, 'admin_user_list.html', {
        'users': users
    })


@login_required
def add_user(request):

    areas = Area.objects.all()

    if request.method == 'POST':

        employee_id = request.POST.get('employee_id')
        username = request.POST.get('username')
        role = request.POST.get('role')
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')

        if password != confirm_password:
            return render(request, 'admin_add_user.html', {
                'error': 'Passwords do not match'
            })

        existing_employee = Profile.objects.filter(
            employee_id=employee_id
        ).exists()

        if existing_employee:
            return render(request, 'admin_add_user.html', {
                'error': f'Employee ID "{employee_id}" is already registered.',
                'areas': areas,
            })
        
        assigned_area_id = request.POST.get('assigned_area')

        assigned_area = None

        if assigned_area_id:
            assigned_area = Area.objects.get(id=assigned_area_id)

        user = User.objects.create_user(
            username=username,
            password=password
        )

        Profile.objects.create(
            user=user,
            role=role,
            employee_id=employee_id,
            assigned_area=assigned_area,
        )

        return redirect('user_list')

    return render(request, 'admin_add_user.html', {
        'areas': areas
    })


@login_required
def edit_user(request, user_id):

    user = User.objects.get(id=user_id)
    profile, created = Profile.objects.get_or_create(user=user)

    areas = Area.objects.all()

    if request.method == 'POST':

        profile.employee_id = request.POST['employee_id']

        user.username = request.POST['username']

        profile.role = request.POST['role']

        assigned_area_id = request.POST.get('assigned_area')

        if assigned_area_id:
            profile.assigned_area = Area.objects.get(id=assigned_area_id)

        else:
            profile.assigned_area = None

        user.save()
        profile.save()

        return redirect('user_list')

    return render(request, 'admin_edit_user.html', {
        'user_obj': user,
        'profile': profile,
        'areas': areas,
    })


@login_required
def delete_user(request, user_id):

    profile = get_object_or_404(Profile, id=user_id)
    profile.user.delete()
    return redirect('user_list')


@login_required
def admin_reports(request):

    report_type = request.GET.get('report_type')
    month = request.GET.get('month')
    day = request.GET.get('day')
    week = request.GET.get('week')
    year = request.GET.get('year')
    current_year = date.today().year

    all_records = WasteRecord.objects.all()
    available_years = sorted({record.date.year for record in all_records}, reverse=True)

    months_by_year = {}
    days_by_year_month = {}
    weeks_by_year_month = {}
    for record in all_records:
        y = record.date.year
        m = record.date.month
        d = record.date.day
        months_by_year.setdefault(y, set()).add(m)
        days_by_year_month.setdefault((y, m), set()).add(d)
        weeks_by_year_month.setdefault((y, m), set()).add((d - 1) // 7 + 1)

    months_by_year = {year_key: sorted(months_by_year[year_key]) for year_key in months_by_year}
    days_by_year_month = {
        f"{y}-{m}": sorted(days_by_year_month[(y, m)])
        for (y, m) in days_by_year_month
    }
    weeks_by_year_month = {
        f"{y}-{m}": sorted(weeks_by_year_month[(y, m)])
        for (y, m) in weeks_by_year_month
    }

    selected_year = int(year) if year and year.isdigit() else None
    if selected_year not in available_years:
        selected_year = available_years[0] if available_years else None

    available_months = months_by_year.get(selected_year, []) if selected_year else []
    selected_month = int(month) if month and month.isdigit() else None
    if selected_month not in available_months:
        selected_month = None

    selected_day = int(day) if day and day.isdigit() else None
    selected_week = int(week) if week and week.isdigit() else None
    month_key = f"{selected_year}-{selected_month}" if selected_year and selected_month else None
    available_days = days_by_year_month.get(month_key, []) if month_key else []
    available_weeks = weeks_by_year_month.get(month_key, []) if month_key else []
    if selected_day not in available_days:
        selected_day = None
    if selected_week not in available_weeks:
        selected_week = None

    records = None
    generated = False
    if report_type and selected_year:
        if report_type == 'yearly':
            generated = True
        elif report_type == 'monthly' and selected_month:
            generated = True
        elif report_type == 'weekly' and selected_month and selected_week:
            generated = True
        elif report_type == 'daily' and selected_month and selected_day:
            generated = True

    if generated:
        records = WasteRecord.objects.filter(date__year=selected_year)
        if report_type == 'daily':
            records = records.filter(
                date__month=selected_month,
                date__day=selected_day
            )
        elif report_type == 'weekly':
            import calendar
            try:
                _, last_day = calendar.monthrange(selected_year, selected_month)
                week_start = 1 + (selected_week - 1) * 7
                week_end = min(week_start + 6, last_day)
                records = records.filter(
                    date__month=selected_month,
                    date__day__gte=week_start,
                    date__day__lte=week_end
                )
            except Exception:
                records = records.filter(date__month=selected_month)
        elif report_type == 'monthly':
            records = records.filter(date__month=selected_month)

        if report_type == 'yearly':
            records = records.order_by(
                'date__month',
                'area',
                'date',
                'time'
            )
        else:
            records = records.order_by('date', 'area', 'time')

    area_groups = (group_records_by_area(records, report_type) if records else [])
    month_choices = [
        (1, 'January'),
        (2, 'February'),
        (3, 'March'),
        (4, 'April'),
        (5, 'May'),
        (6, 'June'),
        (7, 'July'),
        (8, 'August'),
        (9, 'September'),
        (10, 'October'),
        (11, 'November'),
        (12, 'December'),
    ]

    return render(request, 'admin_reports.html', {
        'records': records,
        'area_groups': area_groups,
        'generated': generated,
        'level_legend': build_level_legend(STATUS_LEVEL_COLORS, report_type),
        'years': available_years,
        'available_years': available_years,
        'available_months': available_months,
        'available_days': available_days,
        'available_weeks': available_weeks,
        'month_choices': month_choices,
        'selected_year': selected_year,
        'selected_month': selected_month,
        'selected_week': selected_week,
        'selected_day': selected_day,
        'selected_report_type': report_type,
        'default_year': current_year,
        'json_month_choices': json.dumps(month_choices),
        'json_months_by_year': json.dumps(months_by_year),
        'json_days_by_year_month': json.dumps(days_by_year_month),
        'json_weeks_by_year_month': json.dumps(weeks_by_year_month),
    })


def _int_or_none(value, low=None, high=None):
    """Parse a query-string number, tolerating missing/blank/garbage input.

    Values outside [low, high] are treated as absent so a hand-edited URL
    can't reach calendar/index lookups that would raise.
    """

    try:
        number = int(value)
    except (TypeError, ValueError):
        return None

    if (low is not None and number < low) or (high is not None and number > high):
        return None

    return number


@login_required
def export_pdf(request):
    """Export the waste summary report as a PDF styled with the official
    Bulacan State University (GSO) letterhead.

    Mirrors the on-screen report preview: same records, same per-area
    grouping, and the same alert levels derived from the reporting
    period's thresholds.
    """
    import calendar

    from .reports import build_waste_report_pdf

    report_type = request.GET.get('report_type')
    if report_type not in REPORTING_PERIOD_MAP:
        report_type = 'yearly'

    month = _int_or_none(request.GET.get('month'), 1, 12)
    day = _int_or_none(request.GET.get('day'), 1, 31)
    week = _int_or_none(request.GET.get('week'), 1, 5)
    year = _int_or_none(request.GET.get('year'), 1900, 9999) or date.today().year

    records = WasteRecord.objects.filter(date__year=year)

    if report_type == 'daily' and month and day:
        records = records.filter(date__month=month, date__day=day).order_by('area', 'date', 'time')
    elif report_type == 'weekly' and month and week:
        _, last_day = calendar.monthrange(year, month)
        week_start = 1 + (week - 1) * 7
        week_end = min(week_start + 6, last_day)
        records = records.filter(
            date__month=month,
            date__day__gte=week_start,
            date__day__lte=week_end,
        ).order_by('area', 'date', 'time')
    elif report_type == 'monthly' and month:
        records = records.filter(date__month=month).order_by('area', 'date', 'time')
    else:
        records = records.order_by('date__month', 'area', 'date', 'time')

    MONTHS = ['', 'January', 'February', 'March', 'April', 'May', 'June',
              'July', 'August', 'September', 'October', 'November', 'December']
    if report_type == 'daily' and month and day:
        period_label = f"Daily — {MONTHS[month]} {day}, {year}"
    elif report_type == 'weekly' and month and week:
        period_label = f"Weekly — {MONTHS[month]} {year} (Week {week})"
    elif report_type == 'monthly' and month:
        period_label = f"{MONTHS[month]} {year}"
    else:
        period_label = f"Year {year}"

    pdf_bytes = build_waste_report_pdf(
        records,
        report_type,
        period_label,
        area_groups=group_records_by_area(records, report_type),
        level_legend=build_level_legend(STATUS_LEVEL_COLORS, report_type),
    )

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = (
        f'attachment; filename="GSO_Waste_Report_{period_label.replace(" ", "_")}.pdf"'
    )
    return response


# Presentation details for each reporting period row on the settings page.
THRESHOLD_PERIOD_META = {
    'Today': {
        'key': 'today',
        'label': 'Today',
        'accent': '#16a34a',
        'description': "Daily waste monitoring. Evaluates today's total per waste type.",
    },
    'This Week': {
        'key': 'week',
        'label': 'Weekly',
        'accent': '#7c3aed',
        'description': 'Weekly waste monitoring. Evaluates the total for Week 1 – Week 4 '
                       '(Monday – Sunday).',
    },
    'This Month': {
        'key': 'month',
        'label': 'Monthly',
        'accent': '#2563eb',
        'description': 'Monthly waste monitoring. Evaluates the total for the selected '
                       'month (January – December).',
    },
    'This Year': {
        'key': 'year',
        'label': 'Yearly',
        'accent': '#ea580c',
        'description': "Yearly waste monitoring. Evaluates the sum of the whole year's "
                       'waste for each waste type.',
    },
}

THRESHOLD_FIELDS = ('low_max', 'moderate_max', 'high_max')


@login_required
def threshold_settings(request):

    if request.user.profile.role != 'Head Supervisor':
        return redirect('waste_list')

    thresholds = [
        ThresholdSettings.objects.get_or_create(reporting_period=period)[0]
        for period, _ in ThresholdSettings.REPORTING_PERIOD_CHOICES
    ]

    errors = []

    if request.method == 'POST':

        for threshold in thresholds:
            prefix = THRESHOLD_PERIOD_META[threshold.reporting_period]['key']
            label = THRESHOLD_PERIOD_META[threshold.reporting_period]['label']

            try:
                low, moderate, high = (
                    float(request.POST.get(f'{prefix}_{field}'))
                    for field in THRESHOLD_FIELDS
                )
            except (TypeError, ValueError):
                errors.append(f'{label}: every threshold must be a number.')
                continue

            if not 0 <= low < moderate < high:
                errors.append(
                    f'{label}: values must increase — Low, then Moderate, then High.'
                )
                continue

            threshold.low_max = low
            threshold.moderate_max = moderate
            threshold.high_max = high

        if not errors:
            for threshold in thresholds:
                threshold.save()
            return redirect('threshold_settings')

    for threshold in thresholds:
        meta = THRESHOLD_PERIOD_META[threshold.reporting_period]
        threshold.key = meta['key']
        threshold.label = meta['label']
        threshold.accent = meta['accent']
        threshold.description = meta['description']
        # Pre-formatted range endpoints; the page's JS recomputes these live.
        threshold.low_text = format_amount(threshold.low_max)
        threshold.moderate_text = format_amount(threshold.moderate_max)
        threshold.high_text = format_amount(threshold.high_max)
        threshold.moderate_min = format_amount(threshold.low_max + 0.01)
        threshold.high_min = format_amount(threshold.moderate_max + 0.01)
        threshold.critical_min = format_amount(threshold.high_max + 0.01)

    return render(
        request,
        'threshold_settings.html',
        {
            'thresholds': thresholds,
            'errors': errors,
        }
    )


@login_required
def response_guidelines(request):

    if request.user.profile.role != 'Head Supervisor':
        return redirect('waste_list')

    guidelines, created = ResponseGuidelines.objects.get_or_create(id=1)

    if request.method == 'POST':

        guidelines.low_guideline = request.POST.get(
            'low_guideline'
        )

        guidelines.moderate_guideline = request.POST.get(
            'moderate_guideline'
        )

        guidelines.high_guideline = request.POST.get(
            'high_guideline'
        )

        guidelines.critical_guideline = request.POST.get(
            'critical_guideline'
        )

        guidelines.save()

        return redirect('response_guidelines')

    return render(
        request,
        'response_guidelines.html',
        {
            'guidelines': guidelines,
        }
    )

def dean_dashboard(request):

    area_choices = Area.objects.values_list('area_name', flat=True)
    selected_area = request.GET.get('area', 'All')
    period = request.GET.get('period', 'daily')
    
    qs = WasteRecord.objects.all()
    
    today = date.today()

    if period == "daily":
        qs = qs.filter(date=today)

    elif period == "weekly":
        qs = qs.filter(
        date__gte=today - timedelta(days=7)
    )

    elif period == "monthly":
        qs = qs.filter(
        date__gte=today - timedelta(days=30)
    )

    elif period == "yearly":
        qs = qs.filter(
        date__gte=today - timedelta(days=365)
    )
    if selected_area != 'All':
        qs = qs.filter(area__area_name=selected_area)

    total_waste = qs.aggregate(total=Sum('amount'))['total'] or 0
    total_records = qs.count()

    plastic_total = qs.filter(waste_type='Plastic').aggregate(
        total=Sum('amount'))['total'] or 0
    waste_total = qs.filter(waste_type='Waste').aggregate(
        total=Sum('amount'))['total'] or 0

    critical_count = 0
    for record in qs:
        level, _ = get_level_action(record.amount, period,)
        if level == "Critical":
            critical_count += 1

    monitored_areas = qs.values('area').distinct().count()

    # Breakdown by area and waste type (Top 8)

    area_rows = (
        qs.values('area__area_name')
        .annotate(total=Sum('amount'))
        .order_by('-total')[:8]
    )

    area_labels = [r['area__area_name'] for r in area_rows]

    waste_without_values = []
    plastic_only_values = []
    waste_with_values = []

    for area in area_labels:

        waste_without = qs.filter(
            area__area_name=area,
            waste_type="Waste Without Plastic"
        ).aggregate(total=Sum('amount'))['total'] or 0

        plastic_only = qs.filter(
            area__area_name=area,
            waste_type="Plastic Only"
        ).aggregate(total=Sum('amount'))['total'] or 0

        waste_with = qs.filter(
            area__area_name=area,
            waste_type="Waste With Plastic"
        ).aggregate(total=Sum('amount'))['total'] or 0

        waste_without_values.append(round(waste_without, 2))
        plastic_only_values.append(round(plastic_only, 2))
        waste_with_values.append(round(waste_with, 2))
    
    # Breakdown by alert level
    alert_order = ['Critical', 'High', 'Moderate', 'Low']
    alert_map = {
        r['alert_level']: r['count']
        for r in qs.values('alert_level').annotate(count=Count('id'))
    }
    alert_labels = alert_order
    alert_values = [alert_map.get(level, 0) for level in alert_order]

    recent_records = (
        qs.values(
            'area__area_name',
            'date',
            'waste_type'
        )
        .annotate(
            amount=Sum('amount'),
            latest_submission=Max('submitted_at')
        )
        .order_by('-latest_submission')
    )

    for record in recent_records:
        level, action = get_level_action(
            record['amount'],
            period,
        )
        record['alert_level'] = level

    # ----- Alerts -----
    # Determine each college's CURRENT alert level (from its latest record)
    # so the dean is warned when a college is Critical.
    present_areas = (
    Area.objects.values_list('area_name', flat=True)
    )
    critical_areas = []
    for area in present_areas:
        latest = (
            WasteRecord.objects.filter(area__area_name=area)
            .order_by('-submitted_at')
            .first()
        )
        if latest:
            level, _ = get_level_action(latest.amount, period,)
            if level == "Critical":
                critical_areas.append({
                    "area": area,
                    "amount": latest.amount,
                    "date": latest.date,
                })

    # Alert status for the specific college (when one is selected)
    selected_alert_level = None
    selected_alert_desc = None
    if selected_area != 'All':
        latest_for_selected = (
            WasteRecord.objects.filter(area__area_name=selected_area)
            .order_by('-submitted_at')
            .first()
        )
        if latest_for_selected:
            selected_alert_level, selected_alert_desc = get_level_action( latest_for_selected.amount, period,)
        # Get all Critical messages sent by Supervisors

        # Alert status for selected college
    selected_alert_level = None
    selected_alert_desc = None
    selected_message = None

    if selected_area != 'All':
        latest_for_selected = (
            WasteRecord.objects.filter(area__area_name=selected_area)
            .order_by('-submitted_at')
            .first()
        )

        if latest_for_selected:
            selected_alert_level = latest_for_selected.alert_level
            selected_alert_desc = ALERT_DESCRIPTIONS.get(
                selected_alert_level,
                ''
            )

        selected_message = (
            DeanMessage.objects.filter(
                area__area_name=selected_area
            )
            .order_by('-id')
            .first()
        )

    context = {
        'area_choices': area_choices,
        'selected_area': selected_area,
        'period': period,
        'selected_message': selected_message,
        'total_waste': round(total_waste, 2),
        'total_records': total_records,
        'plastic_total': round(plastic_total, 2),
        'waste_total': round(waste_total, 2),
        'critical_count': critical_count,
        'monitored_areas': monitored_areas,
        'records': recent_records,
        'critical_areas': critical_areas,
        'selected_alert_level': selected_alert_level,
        'selected_alert_desc': selected_alert_desc,
        'area_labels': json.dumps(area_labels),
        'waste_without_values': json.dumps(waste_without_values),
        'plastic_only_values': json.dumps(plastic_only_values),
        'waste_with_values': json.dumps(waste_with_values),
        'alert_labels': json.dumps(alert_labels),
        'alert_values': json.dumps(alert_values),
        'waste_type_values': json.dumps([
            round(plastic_total, 2),
            round(waste_total, 2)
        ]),
    }

    return render(request, 'dean_dashboard.html', context)