"""Template context processors that expose small, cross-page values such as
the Coordinator's critical-college badge count."""

from .models import WasteRecord, Area


def sidebar_badges(request):
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}

    profile = getattr(user, 'profile', None)
    if not profile:
        return {}

    # Number of colleges/areas whose latest record is at Critical level.
    if profile.role in ('Supervisor', 'Head Supervisor'):
        critical = 0
        for area_name in Area.objects.values_list('area_name', flat=True):
            latest = (
                WasteRecord.objects.filter(area__area_name=area_name)
                .order_by('-submitted_at')
                .first()
            )
            if latest and latest.alert_level == 'Critical':
                critical += 1
        return {'critical_college_count': critical}

    return {}
