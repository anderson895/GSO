from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Area, AuditLog, Profile, ThresholdSettings, WasteRecord
from .views import waste_list


class WasteListDashboardTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='spv1', password='secret123')
        self.area = Area.objects.create(area_name='Main Building')
        Profile.objects.create(user=self.user, role='Supervisor', employee_id='SPV-1001')
        ThresholdSettings.objects.get_or_create(id=1)

    def test_mobile_sidebar_markup_is_present_for_key_pages(self):
        self.client.force_login(self.user)

        for route_name in ['waste_list', 'waste_graphs', 'building_status', 'message_dean']:
            response = self.client.get(reverse(route_name))
            self.assertEqual(response.status_code, 200, route_name)
            html = response.content.decode('utf-8')
            self.assertIn('class="mobile-menu-btn"', html, route_name)
            self.assertIn('class="sidebar-overlay"', html, route_name)
            self.assertIn('aria-expanded', html, route_name)

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

    def test_profile_settings_page_has_mobile_sidebar_shell(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('edit_profile'))
        self.assertEqual(response.status_code, 200)

        html = response.content.decode('utf-8')
        self.assertIn('class="mobile-menu-btn"', html)
        self.assertIn('class="sidebar-overlay"', html)
        self.assertIn('aria-expanded="false"', html)
        self.assertIn('aria-hidden="true"', html)
        self.assertIn('id="app-sidebar"', html)
        self.assertIn('.layout.sidebar-mobile-open .sidebar-overlay { opacity: 1; visibility: visible; }', html)

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


class JanitorAuditLogTests(TestCase):
    """The Supervisor's audit log of what the Lead Janitors have done."""

    def setUp(self):
        self.area = Area.objects.create(area_name='Main Building')
        self.other_area = Area.objects.create(area_name='E-Library')

        self.janitor = get_user_model().objects.create_user(
            username='TL-2001', password='secret123'
        )
        Profile.objects.create(
            user=self.janitor, role='Lead Janitor', employee_id='TL-2001'
        )

        self.supervisor = get_user_model().objects.create_user(
            username='SPV-1001', password='secret123'
        )
        Profile.objects.create(
            user=self.supervisor, role='Supervisor', employee_id='SPV-1001'
        )

    def submit_record(self):
        return self.client.post(
            reverse('waste_list'),
            {
                'area': self.area.id,
                'waste_type': 'Waste With Plastic',
                'amount': '3',
                'date': '2026-09-17',
                'time': '10:30',
            },
        )

    def test_submitting_a_record_is_logged(self):
        self.client.force_login(self.janitor)

        self.submit_record()

        log = AuditLog.objects.get()
        self.assertEqual(log.performed_by, self.janitor)
        self.assertEqual(log.action, 'Submitted Waste Record')
        self.assertEqual(log.target, 'Main Building')
        self.assertIn('3 bags', log.details)
        self.assertIn('No photo attached', log.content)

    def test_editing_a_record_logs_the_changed_fields(self):
        self.client.force_login(self.janitor)
        self.submit_record()

        record = WasteRecord.objects.get()

        self.client.post(
            reverse('edit_record', args=[record.id]),
            {
                'area': self.other_area.id,
                'waste_type': 'Waste With Plastic',
                'amount': '7',
                'date': '2026-09-17',
                'time': '10:30',
            },
        )

        log = AuditLog.objects.filter(action='Edited Waste Record').get()
        self.assertEqual(log.target, 'E-Library')
        self.assertIn('Area: Main Building → E-Library', log.content)
        self.assertIn('Bags: 3 → 7', log.content)
        self.assertNotIn('Waste Type', log.content)

    def test_deleting_a_record_is_logged(self):
        self.client.force_login(self.janitor)
        self.submit_record()

        record = WasteRecord.objects.get()
        self.client.get(reverse('delete_record', args=[record.id]))

        log = AuditLog.objects.filter(action='Deleted Waste Record').get()
        self.assertEqual(log.performed_by, self.janitor)
        self.assertEqual(log.target, 'Main Building')
        self.assertIn('3 bags', log.details)

    def test_supervisor_sees_janitor_activity_only(self):
        AuditLog.objects.create(
            performed_by=self.supervisor,
            action='Sent Advisory Message',
            target='Main Building',
        )
        AuditLog.objects.create(
            performed_by=self.janitor,
            action='Submitted Waste Record',
            target='Main Building',
        )

        self.client.force_login(self.supervisor)
        response = self.client.get(reverse('janitor_audit_log'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['tracked_role'], 'Lead Janitor')

        actions = [log.action for log in response.context['audit_entries']]
        self.assertEqual(actions, ['Submitted Waste Record'])

    def test_janitor_cannot_open_the_supervisor_audit_log(self):
        self.client.force_login(self.janitor)

        response = self.client.get(reverse('janitor_audit_log'))

        self.assertRedirects(response, reverse('waste_list'))
