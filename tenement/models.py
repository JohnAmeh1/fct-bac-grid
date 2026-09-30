import random
import string

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

# The Payment model has a ForeignKey field named `property`, which shadows
# Python's built-in `property` decorator inside the class body.
# We capture the built-in here so it can be used as @_property inside Payment.
_property = property

USER_TYPE_CHOICES = (
    ('landlord', 'Landlord'),
    ('staff', 'Staff'),
    ('field_staff', 'Field Staff'),
    ('admin', 'Admin'),
    ('govt_admin', 'Govt Admin'),
)

# Add this block
PROPERTY_TYPE_CHOICES = (
    ('residential', 'Residential'),
    ('commercial', 'Commercial'),
)

VERIFICATION_STATUS_CHOICES = (
    ('verified', 'Verified'),
    ('pending', 'Pending Verification'),
    ('required', 'Verification Required'),
)

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    user_type = models.CharField(max_length=20, choices=USER_TYPE_CHOICES, default='landlord')
    phone_number = models.CharField(max_length=15, blank=True)
    address = models.CharField(max_length=255, blank=True)
    bio = models.TextField(max_length=500, blank=True)
    dark_mode = models.BooleanField(default=False)
    email_verified = models.BooleanField(default=False)
    pending_email = models.EmailField(
        blank=True, default='',
        help_text='A new email address awaiting OTP confirmation. Not yet applied to the account.'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.get_user_type_display()}"


class Property(models.Model):
    owner            = models.ForeignKey(User, on_delete=models.CASCADE, related_name='properties')
    name             = models.CharField(max_length=255)
    address          = models.CharField(max_length=500)
    district         = models.CharField(max_length=100)
    property_type    = models.CharField(max_length=20, choices=PROPERTY_TYPE_CHOICES)  # Now works
    num_units        = models.PositiveIntegerField(default=1)
    num_flats        = models.PositiveIntegerField(default=0, help_text='For residential properties: number of flats/apartments. Used for per-unit rate calculations.')
    latitude         = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude        = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    nearest_community = models.CharField(max_length=120, blank=True, default='')
    property_level   = models.CharField(max_length=50, blank=True, default='')
    main_image       = models.ImageField(upload_to='properties/main/', null=True, blank=True)
    image_1          = models.ImageField(upload_to='properties/additional/', null=True, blank=True)
    image_2          = models.ImageField(upload_to='properties/additional/', null=True, blank=True)
    image_3          = models.ImageField(upload_to='properties/additional/', null=True, blank=True)
    image_4          = models.ImageField(upload_to='properties/additional/', null=True, blank=True)
    image_5          = models.ImageField(upload_to='properties/additional/', null=True, blank=True)
    image_6          = models.ImageField(upload_to='properties/additional/', null=True, blank=True)
    notes            = models.TextField(blank=True)
    verification_status = models.CharField(
        max_length=10, choices=VERIFICATION_STATUS_CHOICES, default='pending',
        help_text='Unverified properties are hidden from shared/admin lists until a staff or admin user verifies them.'
    )
    verified_by      = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='verified_properties')
    verified_at      = models.DateTimeField(null=True, blank=True)
    created_at       = models.DateTimeField(auto_now_add=True)

    @property
    def is_verified(self):
        return self.verification_status == 'verified'

    @property
    def get_primary_image(self):
        """First available image (main image, falling back to the additional slots)."""
        for field_name in ['main_image', 'image_1', 'image_2', 'image_3', 'image_4', 'image_5', 'image_6']:
            image = getattr(self, field_name)
            if image:
                return image
        return None


COMPLAINT_CATEGORY_CHOICES = (
    ('billing',   'Billing Issue'),
    ('property',  'Property Issue'),
    ('technical', 'Technical Problem'),
    ('sanitation', 'Sanitation Issue'),
    ('general',   'General Enquiry'),
    ('other',     'Other'),
)

COMPLAINT_STATUS_CHOICES = (
    ('open',      'Open'),
    ('in_review', 'In Review'),
    ('resolved',  'Resolved'),
    ('closed',    'Closed'),
)


class Complaint(models.Model):
    submitted_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='complaints')
    category     = models.CharField(max_length=30, choices=COMPLAINT_CATEGORY_CHOICES, default='general')
    subject      = models.CharField(max_length=255)
    description  = models.TextField()
    status       = models.CharField(max_length=20, choices=COMPLAINT_STATUS_CHOICES, default='open')
    admin_notes  = models.TextField(blank=True, help_text='Internal notes visible only to admins')
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.get_status_display()}] {self.subject} — {self.submitted_by.username}"


class SiteConfiguration(models.Model):
    """Singleton model — only one row should ever exist (pk=1)."""
    # --- General ---
    site_name          = models.CharField(max_length=100, default='FCT BAC Grid')
    site_tagline       = models.CharField(max_length=255, blank=True, default='Transparent Property Records, Trusted Revenue Collection')
    welcome_message    = models.TextField(
        blank=True,
        default='',
        help_text='Message shown on the dashboard welcome banner.'
    )

    # --- Contact ---
    contact_email      = models.EmailField(blank=True, default='')
    contact_phone      = models.CharField(max_length=20, blank=True, default='')
    contact_address    = models.CharField(max_length=500, blank=True, default='')

    # --- Assessment Year ---
    # Single source of truth for "which year's assessment is currently
    # open" — every page (homepage notices, registration, dashboard,
    # footer) should read this instead of a hardcoded year string, so it
    # can never drift out of sync.
    assessment_year = models.PositiveIntegerField(
        default=2026,
        help_text='The tenement/business/sanitation assessment year currently open for payment.'
    )
    assessment_deadline = models.DateField(
        null=True, blank=True,
        help_text='Payments received after this date attract the late-payment surcharge.'
    )

    # --- System Toggles ---
    allow_registration = models.BooleanField(
        default=True,
        help_text='Allow new landlords to self‑register.'
    )
    maintenance_mode   = models.BooleanField(
        default=False,
        help_text='Put site in read‑only maintenance mode.'
    )
    enable_email_notifications = models.BooleanField(
        default=False,
        help_text='Send email notifications to users (e.g., complaint updates).'
    )

    # --- Limits & Defaults ---
    max_properties_per_landlord = models.PositiveIntegerField(
        default=0,
        help_text='Maximum properties a landlord can register (0 = unlimited).'
    )
    default_pagination_size = models.PositiveIntegerField(
        default=10,
        help_text='Number of items per page in list views.'
    )

    # --- Email Settings ---
    system_email = models.EmailField(
        blank=True,
        default='',
        help_text='Email address used for system notifications (e.g., noreply@bwari.gov).'
    )

    # --- Metadata ---
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='config_updates'
    )

    class Meta:
        verbose_name = 'Site Configuration'

    def __str__(self):
        return f"Site Configuration (last updated {self.updated_at:%Y-%m-%d %H:%M})"

    @classmethod
    def get_config(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
    
    
    
    # Add after existing models

class PaymentRate(models.Model):
    """Admin-created payment rate that applies to properties of a certain type."""
    property_type = models.CharField(
        max_length=20,
        choices=PROPERTY_TYPE_CHOICES,
        null=True,
        blank=True,
        help_text="Select property type unless this is a sanitation rate."
    )
    name = models.CharField(max_length=200, help_text="e.g., 'Annual Tenement Rate 2024'")
    description = models.TextField(blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    is_active = models.BooleanField(default=True, help_text="Only active rates appear for landlords")
    is_per_unit = models.BooleanField(default=False, help_text="If True, this rate is multiplied by the property's number of flats (residential only)")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_payment_rates')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_sanitation = models.BooleanField(
        default=False,
        help_text="If True, this rate applies to ALL users (landlords and tenants) as a monthly environmental sanitation levy."
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        if self.is_sanitation:
            return f"{self.name} - ₦{self.amount} (Sanitation)"
        return f"{self.name} - ₦{self.amount} ({self.get_property_type_display()})"


class Payment(models.Model):
    """Records a payment made by a landlord for a specific property against a rate."""
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('success', 'Successful'),
        ('failed', 'Failed'),
    )
    landlord = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payments')
    # property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='payments')
    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name='payments',
        null=True,          # ← allow null for sanitation payments (no specific property)
        blank=True,
    )
    payment_rate = models.ForeignKey(PaymentRate, on_delete=models.SET_NULL, null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reference = models.CharField(max_length=100, unique=True)  # Paystack reference
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    paid_at = models.DateTimeField(null=True, blank=True)
    paystack_response = models.JSONField(null=True, blank=True)  # Store full response
    created_at = models.DateTimeField(auto_now_add=True)

    expires_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Automatically set based on the payment rate validity. Sanitation payments expire after 30 days, property rates after 1 year.'
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        property_name = self.property.name if self.property else "Environmental Sanitation"
        return f"{self.landlord.username} - {property_name} - {self.reference}"

    @_property
    def is_expired(self):
        """True if the payment has passed its validity window."""
        if self.status != 'success' or not self.expires_at:
            return False
        return timezone.now() > self.expires_at

    @_property
    def days_remaining(self):
        """Days left until expiry. Returns None if not a successful payment."""
        if self.status != 'success' or not self.expires_at:
            return None
        delta = self.expires_at - timezone.now()
        return max(delta.days, 0)
    
class Announcement(models.Model):
    title = models.CharField(max_length=200)
    message = models.TextField()
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='announcements_created')
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True, help_text="Inactive announcements won't appear for users")
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return self.title

class UserAnnouncementRead(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='announcement_reads')
    announcement = models.ForeignKey(Announcement, on_delete=models.CASCADE, related_name='reads')
    read_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('user', 'announcement')


# ====================================================================
# NEW: OTP model for email verification
# ====================================================================
class OTP(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='otp')
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    @classmethod
    def create_otp(cls, user):
        """Generate a new OTP, delete any old one, save and return."""
        cls.objects.filter(user=user).delete()
        code = ''.join(random.choices(string.digits, k=6))
        expires = timezone.now() + timezone.timedelta(minutes=10)
        otp = cls(user=user, code=code, expires_at=expires)
        otp.save()
        return otp

    def is_valid(self):
        return timezone.now() <= self.expires_at

    def verify(self, code):
        if not self.is_valid():
            return False
        if self.code == code:
            self.delete()
            return True
        return False


# ====================================================================
# Support tickets
# ====================================================================
TICKET_CATEGORY_CHOICES = (
    ('property_registration', 'Property registration'),
    ('wrong_property_info',   'Wrong property information'),
    ('payment_issue',         'Payment issue'),
    ('duplicate_property',    'Duplicate property'),
    ('incorrect_assessment',  'Incorrect assessment'),
    ('receipt_problem',       'Receipt problem'),
    ('change_of_ownership',   'Change of ownership'),
    ('technical_problem',     'Technical problem'),
    ('other',                 'Other'),
)

TICKET_STATUS_CHOICES = (
    ('open',        'Open'),
    ('under_review', 'Under Review'),
    ('resolved',    'Resolved'),
)


class SupportTicket(models.Model):
    ticket_number = models.CharField(max_length=20, unique=True, editable=False)
    submitted_by  = models.ForeignKey(User, on_delete=models.CASCADE, related_name='support_tickets')
    category      = models.CharField(max_length=30, choices=TICKET_CATEGORY_CHOICES, default='other')
    description   = models.TextField()
    status        = models.CharField(max_length=20, choices=TICKET_STATUS_CHOICES, default='open')
    staff_notes   = models.TextField(blank=True, help_text='Internal notes visible only to staff/admin')
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.ticket_number

    def save(self, *args, **kwargs):
        if not self.ticket_number:
            year = timezone.now().year
            # Retry a handful of times in the (very unlikely) event of a
            # collision on the random suffix, instead of a hard failure.
            for _ in range(5):
                candidate = f"BAC-{year}-{''.join(random.choices(string.digits, k=6))}"
                if not SupportTicket.objects.filter(ticket_number=candidate).exists():
                    self.ticket_number = candidate
                    break
        super().save(*args, **kwargs)


# ====================================================================
# Notifications
# ====================================================================
class Notification(models.Model):
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    message    = models.CharField(max_length=255)
    link       = models.CharField(max_length=255, blank=True, default='', help_text='Optional URL name/path to link to when clicked.')
    is_read    = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username}: {self.message[:40]}"

    @classmethod
    def notify(cls, user, message, link=''):
        return cls.objects.create(user=user, message=message, link=link)

# ====================================================================
# Emergency alerts
# ====================================================================
EMERGENCY_STATUS_CHOICES = (
    ('open',        'Open'),
    ('in_progress', 'In Progress'),
    ('closed',      'Closed'),
)


# (key, emoji, plain name). The dropdown label is "<emoji> <name>"; the plain
# name is used where an emoji would be awkward (email subject lines, notifications).
EMERGENCY_TYPES = (
    ('fire',             '🔥', 'Fire Outbreak'),
    ('armed_robbery',    '🔫', 'Armed Robbery'),
    ('theft_burglary',   '🏠', 'Theft / Burglary'),
    ('murder',           '⚠️', 'Murder'),
    ('kidnapping',       '🚨', 'Kidnapping'),
    ('road_accident',    '🚗', 'Road Traffic Accident'),
    ('building_collapse', '🏗️', 'Building Collapse'),
    ('flooding',         '🌊', 'Flooding'),
    ('gas_explosion',    '💥', 'Gas Explosion / Gas Leak'),
    ('medical',          '🏥', 'Medical Emergency'),
    ('domestic_violence', '🏠', 'Domestic Violence'),
)
EMERGENCY_TYPE_CHOICES = tuple((key, f"{emoji} {name}") for key, emoji, name in EMERGENCY_TYPES)
EMERGENCY_TYPE_NAMES = {key: name for key, _emoji, name in EMERGENCY_TYPES}
EMERGENCY_TYPE_EMOJIS = {key: emoji for key, emoji, _name in EMERGENCY_TYPES}


class Emergency(models.Model):
    """
    An emergency alert raised by a landlord for one of their own properties.

    Lifecycle: open -> in_progress (staff acknowledged) -> closed. An alert
    may also go straight from open to closed. Who moved it and when is
    recorded on the row itself (in_progress_by/at, closed_by/at).
    """
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='emergencies')
    reported_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='emergencies_reported')
    # Blank only so alerts raised before types existed stay valid; the landlord
    # form (EmergencyReportForm) makes it mandatory for every new alert.
    emergency_type = models.CharField(
        max_length=30, choices=EMERGENCY_TYPE_CHOICES, blank=True, default='', db_index=True,
        help_text='What kind of emergency the landlord selected when raising the alert.',
    )
    # Legacy: free-text details from alerts raised before emergency types were
    # introduced. No longer collected; kept so old alerts lose no information.
    message = models.TextField(blank=True, help_text='Legacy free-text details (no longer collected).')
    status = models.CharField(max_length=20, choices=EMERGENCY_STATUS_CHOICES, default='open', db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    in_progress_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='emergencies_acknowledged'
    )
    in_progress_at = models.DateTimeField(null=True, blank=True)

    closed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='emergencies_closed'
    )
    closed_at = models.DateTimeField(null=True, blank=True)

    email_notified = models.BooleanField(
        default=False,
        help_text='True if at least one staff/admin notification email was delivered for this alert.'
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['status', '-created_at'])]

    def __str__(self):
        return f"[{self.get_status_display()}] {self.type_name} — {self.property.name} — {self.reported_by.username}"

    # NOTE: this model has a field called `property`, so the built-in
    # `property` decorator is shadowed inside the class body — use the
    # module-level `_property` alias instead (same trick as Payment above).
    @_property
    def is_active(self):
        return self.status != 'closed'

    @_property
    def type_name(self):
        """Plain name of the emergency type (no emoji) — safe for subjects and notifications."""
        return EMERGENCY_TYPE_NAMES.get(self.emergency_type, 'Emergency (type not recorded)')

    @_property
    def type_label(self):
        """Emoji + name, e.g. "🔥 Fire Outbreak"; a generic siren for legacy alerts with no type."""
        return f"{EMERGENCY_TYPE_EMOJIS.get(self.emergency_type, '🚨')} {self.type_name}"

    @_property
    def has_coordinates(self):
        return self.property.latitude is not None and self.property.longitude is not None

    @_property
    def google_maps_url(self):
        """
        Google Maps link built from the property's real GPS coordinates, or
        None when the property has no coordinates (templates then show
        "Location unavailable"). Decimals are formatted with format(..., 'f')
        so the URL never contains localised separators or exponents.
        """
        if not self.has_coordinates:
            return None
        lat = format(self.property.latitude, 'f')
        lng = format(self.property.longitude, 'f')
        return f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"