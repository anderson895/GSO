from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Area, Profile, ThresholdSettings, WasteRecord
from .views import waste_list


class WasteListDashboardTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='spv1', password='secret123')
        self.area = Area.objects.create(area_name='Main Building')
        Profile.objects.create(user=self.user, role='Supervisor', employee_id='SPV-1001')
        ThresholdSettings.objects.get_or_create(id=1)

    def test_supervisor_dashboard_shows_no_previous_data_message(self):
        WasteRecord.objects.create(
            user=self.user,
            area=self.area,
            waste_type='Waste With Plastic',
            alert_level='Low',
            amount=3,
            date=date.today(),
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse('waste_list'))

        self.assertEqual(response.context['change_indicator'], 'neutral')
        self.assertEqual(response.context['change_display'], 'No previous data')

    def test_supervisor_dashboard_uses_bag_count_for_feed_items(self):
        WasteRecord.objects.create(
            user=self.user,
            area=self.area,
            waste_type='Waste With Plastic',
            alert_level='Low',
            amount=2,
            date=date.today(),
        )
        WasteRecord.objects.create(
            user=self.user,
            area=self.area,
            waste_type='Plastic Only',
            alert_level='Moderate',
            amount=1,
            date=date.today(),
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse('waste_list'))

        self.assertEqual(len(response.context['data']), 1)
        self.assertEqual(response.context['data'][0]['bags_submitted'], 3)

    def test_export_pdf_daily_report_uses_selected_day(self):
        same_day_record = WasteRecord.objects.create(
            user=self.user,
            area=self.area,
            waste_type='Waste With Plastic',
            alert_level='Low',
            amount=2,
            date=date(2024, 1, 5),
        )
        WasteRecord.objects.create(
            user=self.user,
            area=self.area,
            waste_type='Plastic Only',
            alert_level='Moderate',
            amount=1,
            date=date(2024, 1, 6),
        )

        self.client.force_login(self.user)

        with patch('records.reports.build_waste_report_pdf', return_value=b'pdf') as mock_build:
            response = self.client.get(
                reverse('export_pdf'),
                {'report_type': 'daily', 'month': '1', 'day': '5', 'year': '2024'},
            )

        self.assertEqual(response.status_code, 200)
        records = list(mock_build.call_args.args[0])
        self.assertEqual(records, [same_day_record])
