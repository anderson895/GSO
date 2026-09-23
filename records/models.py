from django.db import models
from django.contrib.auth.models import User

class Profile(models.Model):
    ROLE_CHOICES = [
        ('Head Supervisor', 'Head Supervisor'),
        ('Supervisor', 'Supervisor'),
        ('Lead Janitor', 'Lead Janitor'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    employee_id = models.CharField(max_length=50, unique=True)

    assigned_area = models.ForeignKey(
        'Area',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    def __str__(self):
        return self.user.username


class Area(models.Model):
    area_name = models.CharField(max_length=100)
    status = models.CharField(max_length=50, default='Active')

    def __str__(self):
        return self.area_name

class WasteRecord(models.Model):
    AREA_CHOICES = [
        ('Alvarado Hall', 'Alvarado Hall'),
        ('Activity Center', 'Activity Center'),
        ('Pimentel', 'Pimentel'),
        ('Athletes Building', 'Athletes Building'),
        ('CHTM Building', 'CHTM Building'),
        ('Rizal Park', 'Rizal Park'),
        ('College of Law', 'College of Law'),
        ('CON Canteen', 'CON Canteen'),
        ('Roxas Hall', 'Roxas Hall'),
        ('Carpio Hall', 'Carpio Hall'),
        ('BulSU Resto', 'BulSU Resto'),
        ('Hostel', 'Hostel'),
        ('E-Library', 'E-Library'),
        ('SRLC', 'SRLC'),
        ('CBA Building', 'CBA Building'),
        ('Heroes Park', 'Heroes Park'),
        ('Natividad Hall', 'Natividad Hall'),
        ('Flores Hall', 'Flores Hall'),
        ('Federizo Hall', 'Federizo Hall'),
        ('Valencia Hall', 'Valencia Hall'),
        ('Mendoza Hall', 'Mendoza Hall'),
        ('CCJE Building', 'CCJE Building'),
        ('Campus 2', 'Campus 2'),
        ('Student Lounge', 'Student Lounge'),
    ]

    WASTE_TYPE_CHOICES = [
        ('Waste With Plastic', 'Waste With Plastic'),
        ('Plastic Only', 'Plastic Only'),
        ('Waste Without Plastic', 'Waste Without Plastic'),
    ]

    ALERT_LEVEL_CHOICES = [
        ('Critical', 'Critical'),
        ('High', 'High'),
        ('Moderate', 'Moderate'),
        ('Low', 'Low'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    area = models.ForeignKey(
        'Area',
        on_delete=models.CASCADE
    )
    waste_type = models.CharField(max_length=30, choices=WASTE_TYPE_CHOICES)
    alert_level = models.CharField(max_length=10, choices=ALERT_LEVEL_CHOICES)
    amount = models.PositiveIntegerField(default=0)
    photo = models.FileField(upload_to='report_photos/', null=True, blank=True)
    coordinator_comment = models.TextField(blank=True, null=True)
    coordinator_rating = models.IntegerField(blank=True, null=True)
    date = models.DateField()
    time = models.TimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.area} - {self.waste_type} - {self.date}"


class GeneratedReport(models.Model):
    report_type = models.CharField(max_length=20)
    year = models.IntegerField()
    month = models.CharField(max_length=20)
    generated_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE
    )
    
    generated_at = models.DateTimeField(auto_now_add=True)
    file_name = models.CharField(max_length=255)

    def __str__(self):
        return self.file_name


class DeanMessage(models.Model):
    sender = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='sent_dean_messages'
    )
    area = models.ForeignKey('Area', on_delete=models.CASCADE)
    subject = models.CharField(max_length=200)
    body = models.TextField()
    alert_level = models.CharField(max_length=10, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.subject} ({self.area})"


class ThresholdSettings(models.Model):

    REPORTING_PERIOD_CHOICES = [
        ('Today', 'Today'),
        ('This Week', 'This Week'),
        ('This Month', 'This Month'),
        ('This Year', 'This Year'),
    ]

    reporting_period = models.CharField(
        max_length=20,
        choices=REPORTING_PERIOD_CHOICES,
        unique=True
    )

    low_max = models.FloatField(default=4.00)
    moderate_max = models.FloatField(default=7.00)
    high_max = models.FloatField(default=10.00)

    def __str__(self):
        return f"{self.reporting_period} Waste Threshold Settings"


class ResponseGuidelines(models.Model):
    low_guideline = models.TextField(blank=True)

    moderate_guideline = models.TextField(blank=True)

    high_guideline = models.TextField(blank=True)

    critical_guideline = models.TextField(blank=True)

    def __str__(self):
        return "Response Guidelines"


class AuditLog(models.Model):

    # Supervisor activity, reviewed by the Head Supervisor.
    SUPERVISOR_ACTIONS = [
        'Wrote Waste Record Feedback',
        'Edited Waste Record Feedback',
        'Sent Advisory Message',
    ]

    # Lead Janitor activity, reviewed by the Supervisor.
    JANITOR_ACTIONS = [
        'Submitted Waste Record',
        'Edited Waste Record',
        'Deleted Waste Record',
    ]

    ACTION_CHOICES = [
        (action, action)
        for action in SUPERVISOR_ACTIONS + JANITOR_ACTIONS
    ]

    performed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='hsv_audit_logs'
    )

    action = models.CharField(
        max_length=50,
        choices=ACTION_CHOICES
    )

    target = models.CharField(
        max_length=200
    )

    details = models.TextField(
        blank=True
    )

    content = models.TextField(
        blank=True
    )

    waste_record = models.ForeignKey(
        'WasteRecord',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs'
    )

    waste_record_id_snapshot = models.CharField(
        max_length=20,
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        username = (
            self.performed_by.username
            if self.performed_by
            else 'Deleted User'
        )

        return (
            f"{username} - {self.action} - "
            f"{self.created_at}"
        )