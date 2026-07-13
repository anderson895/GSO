from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_protect
from .models import WasteRecord, Profile, Area, GeneratedReport, ThresholdSettings, ResponseGuidelines, DeanMessage
from .forms import WasteForm, EditWasteForm
from datetime import date, timedelta
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count
from django.http import HttpResponse
from django.db.models.functions import TruncMonth
from itertools import groupby
import json


def group_records_by_area(records):
    """Group waste records per area with a bag subtotal for each area."""
    ordered = sorted(records, key=lambda r: str(r.area))
    groups = []
    for area, items in groupby(ordered, key=lambda r: str(r.area)):
        items = list(items)
        groups.append({
            'area': area,
            'records': items,
            'total_bags': sum(r.amount or 0 for r in items),
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


def _level_ranges():
    """Return (level, range-text) pairs based on the current thresholds."""
    settings = ThresholdSettings.objects.get_or_create(id=1)[0]
    low = settings.low_max
    mod = settings.moderate_max
    high = settings.high_max

    def fmt(v):
        return f"{v:g}"

    return [
        ('Low', f"0 - {fmt(low)} kg"),
        ('Moderate', f"{fmt(low + 0.01)} - {fmt(mod)} kg"),
        ('High', f"{fmt(mod + 0.01)} - {fmt(high)} kg"),
        ('Critical', f"≥ {fmt(high + 0.01)} kg"),
    ]


def build_level_legend(color_map=None):
    """Return legend rows (label, range text, color) based on current thresholds.
    Defaults to the bar-chart color scheme; pass STATUS_LEVEL_COLORS for the
    status-pill scheme used by tables and area cards."""
    if color_map is None:
        color_map = GRAPH_LEVEL_COLORS
    return [
        {'level': level, 'range': rng, 'color': color_map[level]}
        for level, rng in _level_ranges()
    ]


def janitor_required(view_func):
    def wrapper(request, *args, **kwargs):
        if request.user.profile.role != 'Lead Janitor':
            return redirect('waste_list')
        return view_func(request, *args, **kwargs)
    return wrapper


def get_level_action(amount):

    settings = ThresholdSettings.objects.get(id=1)

    if amount <= settings.low_max:
        return 'Low', ALERT_DESCRIPTIONS['Low']

    elif amount <= settings.moderate_max:
        return 'Moderate', ALERT_DESCRIPTIONS['Moderate']

    elif amount <= settings.high_max:
        return 'High', ALERT_DESCRIPTIONS['High']

    return 'Critical', ALERT_DESCRIPTIONS['Critical']


def get_stronger_alert(first, second):
    return first if LEVEL_ORDER.get(first, 0) >= LEVEL_ORDER.get(second, 0) else second


@login_required
@csrf_protect
def waste_list(request):
    form = WasteForm()
    # Read filter selections from query params so both roles can use them
    selected_area = request.GET.get('area', 'All')
    selected_type = request.GET.get('type', 'All')
    type_choices = [choice[0] for choice in WasteRecord.WASTE_TYPE_CHOICES]

    if request.method == 'POST':
        if request.user.profile.role != 'Lead Janitor':
            return redirect('waste_list')
        form = WasteForm(request.POST, request.FILES)
        if form.is_valid():
            record = form.save(commit=False)
            record.user = request.user
            record.alert_level, _ = get_level_action(record.amount)
            record.save()
            return redirect('waste_list')

    if request.user.profile.role == 'Lead Janitor':
        records = WasteRecord.objects.filter(user=request.user).order_by('-submitted_at')
        
        if selected_area != 'All':
            records = records.filter(area__area_name=selected_area)
        if selected_type != 'All':
            records = records.filter(waste_type=selected_type)

    else:
        records = WasteRecord.objects.all().order_by('-submitted_at')

        if selected_area != 'All':
            records = records.filter(area__area_name=selected_area)
        if selected_type != 'All':
            records = records.filter(waste_type=selected_type)
    
    total_records = records.count()
    total_waste_all = records.aggregate(total=Sum('amount'))['total'] or 0

    # Calculate month-over-month change
    today = date.today()
    current_month_start = today.replace(day=1)
    last_month_end = current_month_start - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    
    # Get current month's total
    if request.user.profile.role == 'Lead Janitor':
        # Apply janitor filters to month totals as well
        current_query = WasteRecord.objects.filter(
            user=request.user,
            date__gte=current_month_start,
            date__lte=today
        )
        if selected_area != 'All':
            current_query = current_query.filter(area__area_name=selected_area)
        if selected_type != 'All':
            current_query = current_query.filter(waste_type=selected_type)
        current_month_total = current_query.aggregate(total=Sum('amount'))['total'] or 0

        last_query = WasteRecord.objects.filter(
            user=request.user,
            date__gte=last_month_start,
            date__lt=current_month_start
        )
        if selected_area != 'All':
            last_query = last_query.filter(area__area_name=selected_area)
        if selected_type != 'All':
            last_query = last_query.filter(waste_type=selected_type)
        last_month_total = last_query.aggregate(total=Sum('amount'))['total'] or 0

    else:
        current_query = WasteRecord.objects.filter(
            date__gte=current_month_start,
            date__lte=today
        )

        if selected_area != 'All':
            current_query = current_query.filter(area__area_name=selected_area)
        if selected_type != 'All':
            current_query = current_query.filter(waste_type=selected_type)
        current_month_total = current_query.aggregate(total=Sum('amount'))['total'] or 0
        
        last_query = WasteRecord.objects.filter(
            date__gte=last_month_start,
            date__lt=current_month_start
        )

        if selected_area != 'All':
            last_query = last_query.filter(area__area_name=selected_area)
        if selected_type != 'All':
            last_query = last_query.filter(waste_type=selected_type)
        last_month_total = last_query.aggregate(total=Sum('amount'))['total'] or 0
    
    # Calculate percentage change
    if current_month_total == last_month_total:
        percentage_change = 0
        change_status = 'No Change'
        is_increased = False
    elif last_month_total == 0:
        percentage_change = 100
        change_status = 'Increased'
        is_increased = True
    else:
        percentage_change = ((current_month_total - last_month_total) / last_month_total) * 100
        if current_month_total > last_month_total:
            change_status = 'Increased'
            is_increased = True
        else:
            change_status = 'Decreased'
            is_increased = False

    data = []
    for r in records:
        _, action = get_level_action(r.amount)
        data.append({
            'id': r.id,
            'area': r.area,
            'date': r.date,
            'time': r.time,
            'amount': r.amount,
            'waste_type': r.waste_type,
            'alert_level': r.alert_level,
            'action': action,
            'photo_url': r.photo.url if r.photo else None,
            'janitor': r.user.username if r.user else 'Unknown',
            'submitted_at': r.submitted_at,
            'coordinator_rating': r.coordinator_rating,
            'coordinator_comment': r.coordinator_comment,
        })

    threshold, created = ThresholdSettings.objects.get_or_create(id=1)

    context = {
        'form': form,
        'data': data,
        'total_records': total_records,
        'total_waste_all': total_waste_all,
        'percentage_change': abs(percentage_change),
        'is_increased': is_increased,
        'change_status': change_status,
        'selected_type': selected_type,
        'area_choices': Area.objects.values_list('area_name', flat=True),
        'threshold': threshold,
        'level_legend': build_level_legend(STATUS_LEVEL_COLORS),
    }

    if request.user.profile.role in ('Supervisor', 'Lead Janitor'):
        context['selected_area'] = selected_area
        context['type_choices'] = type_choices
        context['selected_type'] = selected_type

    return render(request, 'waste_list.html', context)


@login_required
@csrf_protect
@janitor_required
def edit_record(request, pk):
    record = get_object_or_404(WasteRecord, id=pk, user=request.user)

    if request.method == 'POST':
        form = EditWasteForm(request.POST, request.FILES, instance=record)
        if form.is_valid():
            edited_record = form.save(commit=False)
            edited_record.alert_level, _ = get_level_action(edited_record.amount)
            edited_record.save()
            return redirect('waste_list')
    else:
        form = EditWasteForm(instance=record)

    return render(request, 'edit.html', {'form': form})


@login_required
@janitor_required
def delete_record(request, pk):
    record = get_object_or_404(WasteRecord, id=pk, user=request.user)
    record.delete()
    return redirect('waste_list')

@login_required
def waste_graphs(request):

    if request.user.profile.role != 'Supervisor':
        return redirect('waste_list')

    period = request.GET.get('period', 'all')
    category = request.GET.get('category', 'both')
    line_period = request.GET.get('line_period', 'yearly')
    selected_area = request.GET.get('area', 'All')

    today = date.today()

    # PERIOD FILTER
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
        start_date = None
        period_title = 'All Time'

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

    bar_colors = [
        GRAPH_LEVEL_COLORS[area_totals[label]['level']]
        for label in labels
    ]

    # SUMMARY
    period_total = sum(totals)

    all_time_qs = WasteRecord.objects.all()

    if selected_area != 'All':
        all_time_qs = all_time_qs.filter(
            area__area_name=selected_area
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

    critical_count = records.filter(
        alert_level='Critical'
    ).count()

    # LINE GRAPH
    if line_period == 'yesterday':
        line_start_date = today - timedelta(days=1)
        line_end_date = today - timedelta(days=1)
        line_title = 'Yesterday'

    elif line_period == 'last_week':
        line_start_date = today - timedelta(days=6)
        line_end_date = today
        line_title = 'Last Week'

    elif line_period == 'last_month':
        line_start_date = today - timedelta(days=29)
        line_end_date = today
        line_title = 'Last Month'

    elif line_period == 'yearly':
        line_start_date = today - timedelta(days=364)
        line_end_date = today
        line_title = 'Last Year'

    else:
        line_start_date = today - timedelta(days=6)
        line_end_date = today
        line_title = 'Last Week'

    line_qs = WasteRecord.objects.filter(
        date__gte=line_start_date,
        date__lte=line_end_date
    )

    date_totals = {}

    if line_period == 'yearly':

        for record in line_qs:

            key = (
                record.date.year,
                record.date.month
            )

            date_totals[key] = (
                date_totals.get(key, 0)
                + record.amount
            )

        line_labels = []
        line_data = []

        y = line_start_date.year
        m = line_start_date.month

        while (y, m) <= (
            line_end_date.year,
            line_end_date.month
        ):

            label_date = date(y, m, 1)

            line_labels.append(
                label_date.strftime('%b %Y')
            )

            line_data.append(
                date_totals.get((y, m), 0)
            )

            if m == 12:
                y += 1
                m = 1
            else:
                m += 1

    else:

        for record in line_qs:

            key = record.date

            date_totals[key] = (
                date_totals.get(key, 0)
                + record.amount
            )

        line_labels = []
        line_data = []

        current = line_start_date

        while current <= line_end_date:

            line_labels.append(
                current.strftime('%m/%d')
            )

            line_data.append(
                date_totals.get(current, 0)
            )

            current += timedelta(days=1)

    import json
    from .models import Area
    area_choices = Area.objects.values_list('area_name', flat=True)
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

        'area_choices': Area.objects.values_list('area_name', flat=True),

        'selected_area': selected_area,

        'level_legend': build_level_legend(),
    })


@login_required
def building_status(request):
    if request.user.profile.role != 'Supervisor':
        return redirect('waste_list')

    if request.method == 'POST':
        selected_area = request.POST.get('current_area', request.GET.get('area', 'All'))
        category = request.POST.get('current_category', request.GET.get('category', 'both'))
        period = request.POST.get('current_period', request.GET.get('period', 'daily'))
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
        start_date = None
        period_title = 'All Time'

    area_choices = Area.objects.values_list(
        'area_name',
        flat=True
    )

    if request.method == 'POST':
        report_id = request.POST.get('report_id')
        if report_id:
            report = get_object_or_404(WasteRecord, id=report_id)
            report.coordinator_comment = request.POST.get('coordinator_comment', '').strip()
            rating = request.POST.get('coordinator_rating')
            try:
                report.coordinator_rating = int(rating) if rating else None
            except (TypeError, ValueError):
                report.coordinator_rating = None
            report.save()
            return redirect(f"{request.path}?area={selected_area}&category={category}&period={period}")

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
        reports = reports.filter(waste_type=category)
    if start_date is not None:
        reports = reports.filter(date__gte=start_date, date__lte=today)

    report_data = []
    for report in reports:
        report_data.append({
            'id': report.id,
            'area': report.area,
            'waste_type': report.waste_type,
            'alert_level': report.alert_level,
            'amount': report.amount,
            'photo_url': report.photo.url if report.photo else None,
            'janitor': report.user.username if report.user else 'Unknown',
            'date': report.date,
            'time': report.time,
            'submitted_at': report.submitted_at,
            'coordinator_comment': report.coordinator_comment,
            'coordinator_rating': report.coordinator_rating,
        })

    selected_total = reports.aggregate(total=Sum('amount'))['total'] or 0
    selected_count = reports.count()
    high_count = reports.filter(alert_level='High').count()
    critical_count = reports.filter(alert_level='Critical').count()

    area_statuses = []
    base_totals = WasteRecord.objects.all()
    if category in [
        'Waste With Plastic',
        'Plastic Only',
        'Waste Without Plastic'
    ]:
        base_totals = base_totals.filter(waste_type=category)
    if start_date is not None:
        base_totals = base_totals.filter(date__gte=start_date, date__lte=today)

    totals_by_area = {}

    for row in base_totals:

        area_name = row.area.area_name

        if area_name not in totals_by_area:
            totals_by_area[area_name] = {
                'total': 0,
                'level': 'Low'
            }

        totals_by_area[area_name]['total'] += row.amount

        totals_by_area[area_name]['level'] = get_stronger_alert(
            totals_by_area[area_name]['level'],
            row.alert_level
        )

    for area in area_choices:
        total = totals_by_area.get(area, {}).get('total', 0)
        level, message = get_level_action(total)
        area_statuses.append({
            'area': area,
            'total': total,
            'status': level,
            'message': message,
        })

    if selected_area != 'All':
        area_statuses = [status for status in area_statuses if status['area'] == selected_area]

    threshold, created = ThresholdSettings.objects.get_or_create(id=1)
    guidelines, created = ResponseGuidelines.objects.get_or_create(id=1)

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
        'level_legend': build_level_legend(STATUS_LEVEL_COLORS),
    })


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


def college_waste_summary(area_name):
    """7-day waste summary + current level for a college/area, used by the
    Message College Dean page."""
    today = date.today()
    start = today - timedelta(days=6)

    qs = WasteRecord.objects.filter(
        area__area_name=area_name,
        date__gte=start,
        date__lte=today,
    )

    reports_submitted = qs.count()
    period_total = qs.aggregate(total=Sum('amount'))['total'] or 0
    average_daily = period_total / 7

    # Classify each day's total into an alert level.
    day_totals = {}
    for record in qs:
        day_totals[record.date] = day_totals.get(record.date, 0) + record.amount

    critical_days = high_days = moderate_days = low_days = 0
    for total in day_totals.values():
        level, _ = get_level_action(total)
        if level == 'Critical':
            critical_days += 1
        elif level == 'High':
            high_days += 1
        elif level == 'Moderate':
            moderate_days += 1
        else:
            low_days += 1

    current_level, current_desc = get_level_action(average_daily)

    return {
        'reports_submitted': reports_submitted,
        'average_daily': round(average_daily, 2),
        'critical_days': critical_days,
        'high_days': high_days,
        'moderate_days': moderate_days,
        'low_days': low_days,
        'current_level': current_level,
        'current_desc': current_desc,
    }


@login_required
@csrf_protect
def message_dean(request):
    """Coordinator (Supervisor) sends an advisory message to a college Dean."""
    if request.user.profile.role != 'Supervisor':
        return redirect('waste_list')

    area_choices = list(Area.objects.values_list('area_name', flat=True))
    selected_area = request.GET.get('area') or (area_choices[0] if area_choices else '')

    if request.method == 'POST':
        selected_area = request.POST.get('area', selected_area)
        subject = request.POST.get('subject', '').strip()
        body = request.POST.get('body', '').strip()
        area = Area.objects.filter(area_name=selected_area).first()

        if area and subject and body:
            summary = college_waste_summary(selected_area)
            DeanMessage.objects.create(
                sender=request.user,
                area=area,
                subject=subject,
                body=body,
                alert_level=summary['current_level'],
            )
            messages.success(request, f'Message sent to the Dean of {selected_area}.')
            return redirect(f"{request.path}?area={selected_area}")

        messages.error(request, 'Please complete all fields before sending.')

    summary = college_waste_summary(selected_area) if selected_area else None
    sent_messages = DeanMessage.objects.filter(sender=request.user)[:10]

    default_subject = (
        f"Urgent: {summary['current_level']} Waste Level in {selected_area}"
        if summary else ''
    )
    default_body = (
        f"Good day, Dean.\n\n"
        f"This is to inform you that the waste level in {selected_area} is currently "
        f"{summary['current_level'].upper()}.\n"
        f"Immediate action is necessary to address the increasing waste "
        f"accumulation in your area.\n\n"
        f"Please advise your staff to prioritize waste collection and proper disposal.\n\n"
        f"Thank you."
        if summary else ''
    )

    return render(request, 'message_college_dean.html', {
        'area_choices': area_choices,
        'selected_area': selected_area,
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

    trend_period = request.GET.get('trend_period', 'last_week')
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
    if trend_period == "today":
        start_date = today
        end_date = today

    elif trend_period == "last_week":
        start_date = today - timedelta(days=6)
        end_date = today

    elif trend_period == "last_month":
        start_date = today - timedelta(days=30)
        end_date = today

    elif trend_period == "this_year":
        start_date = date(today.year, 1, 1)
        end_date = today

    else:
        start_date = today - timedelta(days=6)
        end_date = today

    graph_qs = graph_qs.filter(
        date__gte=start_date,
        date__lte=end_date
    )

    # BUILD GRAPH
    if trend_period == "this_year":

        monthly_data = (
            graph_qs
            .annotate(month=TruncMonth("date"))
            .values("month")
            .annotate(total=Sum("amount"))
            .order_by("month")
        )

        monthly_totals = {
            item["month"].month: float(item["total"])
            for item in monthly_data
        }

        graph_labels = [
            "Jan", "Feb", "Mar", "Apr",
            "May", "Jun", "Jul", "Aug",
            "Sep", "Oct", "Nov", "Dec"
        ]

        graph_values = [
            monthly_totals.get(month, 0)
            for month in range(1, 13)
        ]

    else:

        graph_labels = []
        graph_values = []

        # THIS YEAR (Monthly)
        if trend_period == "this_year":

            monthly_totals = (
                graph_qs
                .annotate(month=TruncMonth('date'))
                .values('month')
                .annotate(total=Sum('amount'))
                .order_by('month')
            )

            month_data = {}

            for item in monthly_totals:
                month_data[item['month'].month] = float(item['total'])

            for month in range(1, 13):

                graph_labels.append(
                    date(today.year, month, 1).strftime('%b')
                )

                graph_values.append(
                    month_data.get(month, 0)
                )

        # TODAY / LAST WEEK / LAST MONTH
        else:

            date_totals = {}

            for record in graph_qs:
                date_totals[record.date] = (
                    date_totals.get(record.date, 0)
                    + record.amount
                )

            current = start_date

            while current <= end_date:

                graph_labels.append(
                    current.strftime('%b %d')
                )

                graph_values.append(
                    float(date_totals.get(current, 0))
                )

                current += timedelta(days=1)

    context = {
        'total_users': total_users,
        'total_records': total_records,
        'total_waste': total_waste,
        'total_areas': total_areas,

        'trend_period': trend_period,
        'trend_category': trend_category,

        'graph_labels': json.dumps(graph_labels),
        'graph_values': json.dumps(graph_values),
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

    year = request.GET.get('year')

    records = None
    generated = bool(report_type and year)

    if generated:

        records = WasteRecord.objects.filter(
            date__year=year
        )

        if report_type == 'monthly' and month:

            records = records.filter(
                date__month=month
            ).order_by('area', 'date', 'time')

        elif report_type == 'yearly':

            records = records.order_by(
                'date__month',
                'area',
                'date',
                'time'
            )

    area_groups = group_records_by_area(records) if records else []

    return render(request, 'admin_reports.html', {
        'records': records,
        'area_groups': area_groups,
        'generated': generated,
        'default_year': date.today().year,
        'level_legend': build_level_legend(STATUS_LEVEL_COLORS),
    })


@login_required
def export_pdf(request):
    """Export the waste summary report as a PDF styled with the official
    Bulacan State University (GSO) letterhead."""
    from .reports import build_waste_report_pdf

    report_type = request.GET.get('report_type')
    month = request.GET.get('month')
    year = request.GET.get('year')

    records = WasteRecord.objects.filter(date__year=year)

    if report_type == 'monthly' and month:
        records = records.filter(date__month=month).order_by('area', 'date', 'time')
    else:
        records = records.order_by('date__month', 'area', 'date', 'time')

    MONTHS = ['', 'January', 'February', 'March', 'April', 'May', 'June',
              'July', 'August', 'September', 'October', 'November', 'December']
    if report_type == 'monthly' and month:
        try:
            period_label = f"{MONTHS[int(month)]} {year}"
        except (ValueError, IndexError):
            period_label = f"{year}"
    else:
        period_label = f"Year {year}"

    pdf_bytes = build_waste_report_pdf(records, report_type or 'yearly', period_label)

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = (
        f'attachment; filename="GSO_Waste_Report_{period_label.replace(" ", "_")}.pdf"'
    )
    return response


@login_required
def threshold_settings(request):

    if request.user.profile.role != 'Head Supervisor':
        return redirect('waste_list')

    threshold, created = ThresholdSettings.objects.get_or_create(id=1)

    if request.method == 'POST':

        threshold.low_max = request.POST.get('low_max')

        threshold.moderate_max = request.POST.get('moderate_max')

        threshold.high_max = request.POST.get('high_max')

        threshold.save()

        return redirect('threshold_settings')

    threshold_choices = [
        round(x * 0.25, 2)
        for x in range(1, 121)
    ]

    return render(
        request,
        'threshold_settings.html',
        {
            'threshold': threshold,
            'threshold_choices': threshold_choices,
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

    qs = WasteRecord.objects.all()
    if selected_area != 'All':
        qs = qs.filter(area__area_name=selected_area)

    total_waste = qs.aggregate(total=Sum('amount'))['total'] or 0
    total_records = qs.count()

    plastic_total = qs.filter(waste_type='Plastic').aggregate(
        total=Sum('amount'))['total'] or 0
    waste_total = qs.filter(waste_type='Waste').aggregate(
        total=Sum('amount'))['total'] or 0

    critical_count = qs.filter(alert_level='Critical').count()
    monitored_areas = qs.values('area').distinct().count()

    # Breakdown by area (top 8 by amount)
    area_rows = (
        qs.values('area')
        .annotate(total=Sum('amount'))
        .order_by('-total')[:8]
    )
    area_labels = [r['area'] for r in area_rows]
    area_values = [round(r['total'] or 0, 2) for r in area_rows]

    # Breakdown by alert level
    alert_order = ['Critical', 'High', 'Moderate', 'Low']
    alert_map = {
        r['alert_level']: r['count']
        for r in qs.values('alert_level').annotate(count=Count('id'))
    }
    alert_labels = alert_order
    alert_values = [alert_map.get(level, 0) for level in alert_order]

    recent_records = qs.order_by('-submitted_at')[:8]

    # ----- Messages from Coordinators -----
    dean_messages_qs = DeanMessage.objects.all()
    if selected_area != 'All':
        dean_messages_qs = dean_messages_qs.filter(area__area_name=selected_area)
    dean_messages = list(dean_messages_qs.select_related('area', 'sender')[:15])
    unread_messages = sum(1 for m in dean_messages if not m.is_read)

    # Mark the messages the Dean is now viewing as read, so the notification
    # badge clears the next time the dashboard loads.
    unread_ids = [m.id for m in dean_messages if not m.is_read]
    if unread_ids:
        DeanMessage.objects.filter(id__in=unread_ids).update(is_read=True)

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
        if latest and latest.alert_level == 'Critical':
            critical_areas.append({
                'area': area,
                'amount': latest.amount,
                'date': latest.date,
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
            selected_alert_level = latest_for_selected.alert_level
            selected_alert_desc = ALERT_DESCRIPTIONS.get(selected_alert_level, '')

    context = {
        'area_choices': area_choices,
        'selected_area': selected_area,
        'total_waste': round(total_waste, 2),
        'total_records': total_records,
        'plastic_total': round(plastic_total, 2),
        'waste_total': round(waste_total, 2),
        'critical_count': critical_count,
        'monitored_areas': monitored_areas,
        'records': recent_records,
        'critical_areas': critical_areas,
        'dean_messages': dean_messages,
        'unread_messages': unread_messages,
        'selected_alert_level': selected_alert_level,
        'selected_alert_desc': selected_alert_desc,
        'area_labels': json.dumps(area_labels),
        'area_values': json.dumps(area_values),
        'alert_labels': json.dumps(alert_labels),
        'alert_values': json.dumps(alert_values),
        'waste_type_values': json.dumps([round(plastic_total, 2), round(waste_total, 2)]),
    }

    return render(request, 'dean_dashboard.html', context)