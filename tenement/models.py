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
)

# Add this block
PROPERTY_TYPE_CHOICES = (
    ('residential', 'Residential'),
    ('commercial', 'Commercial'),
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
    created_at       = models.DateTimeField(auto_now_add=True)


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