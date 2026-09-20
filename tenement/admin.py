
# Register your models here.
from django.contrib import admin
from django.contrib.auth.models import User
from django.utils.html import format_html
from django.utils import timezone

from .models import (
    UserProfile,
    Property,
    Complaint,
    SiteConfiguration,
    PaymentRate,
    Payment,
    Announcement,
    UserAnnouncementRead,
    OTP,
)


# ---------------------------------------------------------------------------
# Inline: UserProfile inside User admin
# ---------------------------------------------------------------------------
class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = "Profile"
    fields = ("user_type", "phone_number", "address", "bio", "email_verified", "created_at")
    readonly_fields = ("created_at",)


class UserAdmin(admin.ModelAdmin):
    inlines = (UserProfileInline,)
    list_display = ("username", "email", "first_name", "last_name", "get_user_type", "is_active", "date_joined")
    list_filter = ("is_active", "is_staff", "userprofile__user_type")
    search_fields = ("username", "email", "first_name", "last_name")
    ordering = ("-date_joined",)

    @admin.display(description="User Type")
    def get_user_type(self, obj):
        try:
            return obj.userprofile.get_user_type_display()
        except UserProfile.DoesNotExist:
            return "—"


# Unregister the default User admin and re-register with our extended one
admin.site.unregister(User)
admin.site.register(User, UserAdmin)


# ---------------------------------------------------------------------------
# UserProfile
# ---------------------------------------------------------------------------
@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "user_type", "phone_number", "email_verified", "created_at")
    list_filter = ("user_type", "email_verified")
    search_fields = ("user__username", "user__email", "phone_number")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)


# ---------------------------------------------------------------------------
# Property
# ---------------------------------------------------------------------------
class PropertyImageInline(admin.TabularInline):
    model = Property
    # Not a true inline – images are fields on the same model.
    # We expose image previews via readonly fields on PropertyAdmin below.
    extra = 0


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = (
        "name", "owner", "property_type", "district",
        "num_units", "num_flats", "created_at", "thumbnail",
    )
    list_filter = ("property_type", "district")
    search_fields = ("name", "address", "owner__username", "owner__email")
    readonly_fields = ("created_at", "thumbnail", "image_gallery")
    ordering = ("-created_at",)
    fieldsets = (
        ("Basic Information", {
            "fields": ("owner", "name", "address", "district", "property_type", "num_units", "num_flats", "notes"),
        }),
        ("Location", {
            "fields": ("latitude", "longitude"),
            "classes": ("collapse",),
        }),
        ("Images", {
            "fields": ("main_image", "thumbnail", "image_1", "image_2", "image_3", "image_4", "image_5", "image_6"),
        }),
        ("Metadata", {
            "fields": ("created_at",),
        }),
    )

    @admin.display(description="Thumbnail")
    def thumbnail(self, obj):
        if obj.main_image:
            return format_html(
                '<img src="{}" style="height:60px;border-radius:4px;" />', obj.main_image.url
            )
        return "—"

    @admin.display(description="Gallery")
    def image_gallery(self, obj):
        images = [
            getattr(obj, f"image_{i}") for i in range(1, 7)
            if getattr(obj, f"image_{i}")
        ]
        if not images:
            return "—"
        return format_html(
            " ".join(
                f'<img src="{img.url}" style="height:50px;margin:2px;border-radius:3px;" />'
                for img in images
            )
        )


# ---------------------------------------------------------------------------
# Complaint
# ---------------------------------------------------------------------------
@admin.register(Complaint)
class ComplaintAdmin(admin.ModelAdmin):
    list_display = ("subject", "submitted_by", "category", "status", "created_at", "updated_at")
    list_filter = ("status", "category")
    search_fields = ("subject", "description", "submitted_by__username")
    readonly_fields = ("submitted_by", "created_at", "updated_at")
    ordering = ("-created_at",)
    fieldsets = (
        ("Complaint Details", {
            "fields": ("submitted_by", "category", "subject", "description"),
        }),
        ("Resolution", {
            "fields": ("status", "admin_notes"),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("submitted_by")


# ---------------------------------------------------------------------------
# SiteConfiguration  (singleton — hide add/delete)
# ---------------------------------------------------------------------------
@admin.register(SiteConfiguration)
class SiteConfigurationAdmin(admin.ModelAdmin):
    list_display = ("site_tagline", "allow_registration", "maintenance_mode", "enable_email_notifications", "updated_at")
    readonly_fields = ("updated_at", "updated_by")
    fieldsets = (
        ("General", {
            "fields": ("site_tagline", "welcome_message"),
        }),
        ("Contact", {
            "fields": ("contact_email", "contact_phone", "contact_address"),
        }),
        ("System Toggles", {
            "fields": ("allow_registration", "maintenance_mode", "enable_email_notifications"),
        }),
        ("Limits & Defaults", {
            "fields": ("max_properties_per_landlord", "default_pagination_size"),
        }),
        ("Email Settings", {
            "fields": ("system_email",),
        }),
        ("Metadata", {
            "fields": ("updated_at", "updated_by"),
            "classes": ("collapse",),
        }),
    )

    def has_add_permission(self, request):
        # Only one config row should ever exist
        return not SiteConfiguration.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


# ---------------------------------------------------------------------------
# PaymentRate
# ---------------------------------------------------------------------------
@admin.register(PaymentRate)
class PaymentRateAdmin(admin.ModelAdmin):
    list_display = ("name", "property_type", "amount", "is_active", "is_per_unit", "created_by", "created_at")
    list_filter = ("property_type", "is_active", "is_per_unit")
    search_fields = ("name", "description")
    readonly_fields = ("created_at", "updated_at", "created_by")
    ordering = ("-created_at",)
    fieldsets = (
        ("Rate Details", {
            "fields": ("property_type", "name", "description", "amount"),
        }),
        ("Settings", {
            "fields": ("is_active", "is_per_unit"),
        }),
        ("Metadata", {
            "fields": ("created_by", "created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    def save_model(self, request, obj, form, change):
        if not obj.pk:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


# ---------------------------------------------------------------------------
# Payment
# ---------------------------------------------------------------------------
@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "reference", "landlord", "property_name", "payment_rate",
        "amount", "status", "paid_at", "expires_at", "expiry_status",
    )
    list_filter = ("status",)
    search_fields = ("reference", "landlord__username", "property__name")
    readonly_fields = ("reference", "paystack_response", "created_at", "paid_at", "expires_at", "expiry_badge")
    ordering = ("-created_at",)
    fieldsets = (
        ("Payment Info", {
            "fields": ("landlord", "property", "payment_rate", "amount", "reference", "status"),
        }),
        ("Validity", {
            "fields": ("paid_at", "expires_at", "expiry_badge"),
        }),
        ("Raw Response", {
            "fields": ("paystack_response",),
            "classes": ("collapse",),
        }),
        ("Metadata", {
            "fields": ("created_at",),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description="Property")
    def property_name(self, obj):
        return obj.property.name if obj.property else "—"

    @admin.display(description="Expiry")
    def expiry_status(self, obj):
        if obj.status != "success" or not obj.expires_at:
            return "—"
        if timezone.now() > obj.expires_at:
            return format_html('<span style="color:red;font-weight:bold;">Expired</span>')
        return format_html('<span style="color:green;">Active</span>')

    @admin.display(description="Expiry Status")
    def expiry_badge(self, obj):
        return self.expiry_status(obj)


# ---------------------------------------------------------------------------
# Announcement + inline reads
# ---------------------------------------------------------------------------
class UserAnnouncementReadInline(admin.TabularInline):
    model = UserAnnouncementRead
    extra = 0
    readonly_fields = ("user", "read_at")
    can_delete = False
    verbose_name_plural = "Read By"


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ("title", "is_active", "created_by", "created_at", "read_count")
    list_filter = ("is_active",)
    search_fields = ("title", "message")
    readonly_fields = ("created_at", "created_by")
    ordering = ("-created_at",)
    inlines = (UserAnnouncementReadInline,)

    @admin.display(description="Reads")
    def read_count(self, obj):
        return obj.reads.count()

    def save_model(self, request, obj, form, change):
        if not obj.pk:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


# ---------------------------------------------------------------------------
# UserAnnouncementRead
# ---------------------------------------------------------------------------
@admin.register(UserAnnouncementRead)
class UserAnnouncementReadAdmin(admin.ModelAdmin):
    list_display = ("user", "announcement", "read_at")
    list_filter = ("announcement",)
    search_fields = ("user__username", "announcement__title")
    readonly_fields = ("user", "announcement", "read_at")
    ordering = ("-read_at",)

    def has_add_permission(self, request):
        return False


# ---------------------------------------------------------------------------
# OTP
# ---------------------------------------------------------------------------
@admin.register(OTP)
class OTPAdmin(admin.ModelAdmin):
    list_display = ("user", "created_at", "expires_at", "is_valid_display")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("user", "code", "created_at", "expires_at")
    ordering = ("-created_at",)

    @admin.display(description="Valid?", boolean=True)
    def is_valid_display(self, obj):
        return timezone.now() <= obj.expires_at

    def has_add_permission(self, request):
        return False