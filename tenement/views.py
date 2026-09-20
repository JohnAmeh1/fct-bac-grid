import io
import csv
import re
import uuid
import threading
from decimal import Decimal
import openpyxl
import json
import qrcode
import base64
from django.db.models import Sum
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from django.db.models import Q
from django.db import models as django_models
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.utils import timezone
from functools import wraps
from datetime import timedelta
from django.core.cache import cache
from django.utils.text import slugify

from .forms import (
    SignupForm, LoginForm, ProfileUpdateForm, PropertyRegistrationForm,
    PropertyEditForm, PropertyBulkUploadForm, ComplaintForm,
    AdminComplaintUpdateForm, SiteConfigurationForm, PaymentRateForm,
    FixedResidentialRateForm, AnnouncementForm, StaffLandlordCreationForm,
    StaffPropertyRegistrationForm, OTPVerificationForm,
    ForgotPasswordForm, ForgotPasswordOTPForm, ResetPasswordForm,
)
from .models import (
    UserProfile, Property, Complaint, SiteConfiguration, PaymentRate, Payment,
    Announcement, UserAnnouncementRead, OTP,
)
from django.contrib.auth.hashers import make_password
from io import BytesIO
from django.conf import settings
from django.urls import reverse
from django.contrib.auth.decorators import user_passes_test
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
import requests
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt

# Helper: email sending
from django.core.mail import send_mail

def send_otp_email(user, otp_code):
    subject = 'Email Verification – Bwari Tenement System'
    message = (
        f"Hello {user.first_name or user.username},\n\n"
        f"Your verification code is:\n\n"
        f"    {otp_code}\n\n"
        f"It expires in 10 minutes. Please enter it on the verification page."
    )
    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )
        return True
    except Exception as e:
        import traceback
        traceback.print_exc()        # <-- prints full error to console
        print(f"Email error: {e}")
        return False
    # try:
    #     send_mail(
    #         subject,
    #         message,
    #         settings.DEFAULT_FROM_EMAIL,
    #         [user.email],
    #         fail_silently=False,
    #     )
    #     return True
    # except Exception as e:
    #     import traceback
    #     traceback.print_exc()        # <-- prints full error to console
    #     print(f"Email error: {e}")
    #     return False

# Decorator to require verified email for certain views
def verified_email_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.user.is_authenticated and hasattr(request.user, 'userprofile'):
            if request.user.userprofile.email_verified:
                return view_func(request, *args, **kwargs)
        return redirect('verify_email')
    return wrapper


# ── Property Payment helpers ─────────────────────────────────────────────────

def get_active_property_rates(property_obj):
    if not property_obj:
        return PaymentRate.objects.none()
    return PaymentRate.objects.filter(
        property_type=property_obj.property_type,
        is_active=True,
        is_sanitation=False,
    ).order_by('-created_at')


def get_property_payment_status(property_obj):
    if not property_obj or not property_obj.owner:
        return 'not_paid'

    active_rates = list(get_active_property_rates(property_obj))
    if not active_rates:
        return 'not_paid'

    now = timezone.now()
    paid_count = 0
    for rate in active_rates:
        valid_payment = Payment.objects.filter(
            landlord=property_obj.owner,
            property=property_obj,
            payment_rate=rate,
            status='success',
        ).filter(
            django_models.Q(expires_at__isnull=True) | django_models.Q(expires_at__gt=now)
        ).exists()
        if valid_payment:
            paid_count += 1

    if paid_count == len(active_rates):
        return 'paid'
    if paid_count > 0:
        return 'pending'
    return 'not_paid'


def is_property_fully_paid(property_obj):
    return get_property_payment_status(property_obj) == 'paid'

def get_latest_valid_payment(property_obj, rate):
    now = timezone.now()
    return Payment.objects.filter(
        landlord=property_obj.owner,
        property=property_obj,
        payment_rate=rate,
        status='success',
    ).filter(
        django_models.Q(expires_at__isnull=True) | django_models.Q(expires_at__gt=now)
    ).order_by('-paid_at').first()

MANAGED_PROPERTY_ROLES = ['admin', 'staff', 'field_staff']


def staff_or_admin_required(view_func):
    def check_user(user):
        return user.is_authenticated and hasattr(user, 'userprofile') and user.userprofile.user_type in MANAGED_PROPERTY_ROLES
    return user_passes_test(check_user)(view_func)


def user_can_manage_property(user, property_obj):
    if not user or not user.is_authenticated:
        return False
    if user == property_obj.owner:
        return True
    profile = getattr(user, 'userprofile', None)
    return bool(
        profile and profile.user_type in MANAGED_PROPERTY_ROLES
    ) or bool(user.is_staff and profile and profile.user_type in ['staff', 'field_staff', 'admin'])


DUMMY_PROPERTY_PASSWORDS = ['12345678']


def get_property_sanitation_status(property_obj):
    if not property_obj or not property_obj.owner:
        return 'not_paid'

    sanitation_rates = list(PaymentRate.objects.filter(is_sanitation=True, is_active=True).order_by('-created_at'))
    if not sanitation_rates:
        return 'not_paid'

    now = timezone.now()
    paid_count = 0
    for rate in sanitation_rates:
        valid_payment = Payment.objects.filter(
            landlord=property_obj.owner,
            status='success',
            payment_rate=rate,
        ).filter(
            django_models.Q(property__isnull=True) | django_models.Q(property=property_obj),
            django_models.Q(expires_at__isnull=True) | django_models.Q(expires_at__gt=now),
        ).exists()
        if valid_payment:
            paid_count += 1

    if paid_count == len(sanitation_rates):
        return 'paid'
    if paid_count > 0:
        return 'pending'
    return 'not_paid'


def is_property_sanitation_paid(property_obj):
    return get_property_sanitation_status(property_obj) == 'paid'


def generate_dummy_property_credentials(property_ref, password_index=None):
    base = slugify(str(property_ref or 'property')) or 'property'
    suffix = uuid.uuid4().hex[:8]
    username = f"{base[:20]}-{suffix}" if base else f"property-{suffix}"
    username = username.lower()
    username = re.sub(r'[^a-z0-9\-_]+', '-', username)
    username = username.strip('-_')[:30]
    if not username:
        username = f"property-{suffix}"
    email = f"{username}@bwariproperty.local"
    password = DUMMY_PROPERTY_PASSWORDS[0]
    return username, email, password


def get_paginator_page_range(page_obj, siblings=2, boundary=1):
    """Return a compact but complete page list with ellipses for gaps."""
    page_number = page_obj.number
    total_pages = page_obj.paginator.num_pages
    if total_pages <= (siblings * 2) + boundary * 2 + 3:
        return list(range(1, total_pages + 1))

    page_range = []
    left_window = max(1, page_number - siblings)
    right_window = min(total_pages, page_number + siblings)

    for num in range(1, boundary + 1):
        page_range.append(num)
    if left_window > boundary + 1:
        page_range.append('…')
    for num in range(left_window, right_window + 1):
        if num > boundary and num <= total_pages - boundary:
            page_range.append(num)
    if right_window < total_pages - boundary:
        page_range.append('…')
    for num in range(total_pages - boundary + 1, total_pages + 1):
        if num > 0:
            page_range.append(num)

    deduped = []
    seen = set()
    for item in page_range:
        if item == '…':
            deduped.append(item)
            continue
        if item not in seen:
            deduped.append(item)
            seen.add(item)
    return deduped


def import_properties_from_uploaded_file(uploaded_file, progress_callback=None, max_preview_rows=25):
    if uploaded_file is None:
        return 0, []

    file_name = getattr(uploaded_file, 'name', '').lower()
    rows = []

    def progress(current, total, created_count, message):
        if progress_callback:
            progress_callback(current, total, created_count, message)

    def normalize_coordinate(value):
        if value is None or str(value).strip() == '':
            return None
        try:
            return Decimal(str(value).strip()).quantize(Decimal('0.000001'))
        except Exception:
            return None

    try:
        uploaded_file.seek(0)
        if file_name.endswith('.csv'):
            text = uploaded_file.read().decode('utf-8-sig')
            rows = list(csv.DictReader(io.StringIO(text)))
        else:
            workbook = openpyxl.load_workbook(io.BytesIO(uploaded_file.read()), read_only=True, data_only=True)
            sheet = workbook.active
            raw_rows = list(sheet.iter_rows(values_only=True))
            if not raw_rows:
                return 0, []
            headers = [str(value).strip().lower() if value is not None else '' for value in raw_rows[0]]
            for row in raw_rows[1:]:
                mapping = {}
                for index, header in enumerate(headers):
                    if index < len(row):
                        key = header or f'column_{index + 1}'
                        mapping[key] = row[index]
                if mapping:
                    rows.append(mapping)
    except Exception:
        return 0, []

    def get_value(mapping, *keys):
        for key in keys:
            if key in mapping and mapping[key] is not None and str(mapping[key]).strip() != '':
                return mapping[key]
        return ''

    existing_usernames = set(User.objects.values_list('username', flat=True))
    existing_property_signatures = set()
    for existing_name, existing_address, existing_district, existing_latitude, existing_longitude in Property.objects.values_list(
        'name', 'address', 'district', 'latitude', 'longitude'
    ):
        existing_property_signatures.add((
            str(existing_name or '').strip().lower(),
            str(existing_address or '').strip().lower(),
            str(existing_district or '').strip().lower(),
            str(existing_latitude) if existing_latitude is not None else '',
            str(existing_longitude) if existing_longitude is not None else '',
        ))

    valid_rows = []
    seen_usernames = set(existing_usernames)
    total_rows = len(rows)

    for row_index, row in enumerate(rows, start=1):
        mapping = {}
        for key, value in row.items():
            if key is None:
                continue
            mapping[re.sub(r'[^a-z0-9]+', '', str(key).lower())] = value

        property_ref = get_value(
            mapping,
            'bulkpropertyid', 'bulk_property_id', 'bulkproperty',
            'bacgridid', 'bac_grid_id', 'gridid', 'propertyid', 'property_id',
            'propertynumber', 'property_number', 'id', 'propertyname', 'name', 'property_name'
        )
        name = get_value(
            mapping,
            'propertyname', 'name', 'property_name', 'title', 'propertytitle',
            'bulkpropertyid', 'bulk_property_id', 'bacgridid', 'bac_grid_id'
        )
        address = get_value(mapping, 'address', 'propertyaddress', 'location', 'streetaddress', 'propertylocation')
        district = get_value(mapping, 'district', 'area', 'zone', 'localgovtarea')
        property_type = get_value(mapping, 'propertytype', 'type', 'property_type', 'category')
        latitude = get_value(mapping, 'latitude', 'lat')
        longitude = get_value(mapping, 'longitude', 'lng', 'lon', 'long')
        num_units = get_value(mapping, 'num_units', 'numberofunits', 'units', 'unitcount')
        num_flats = get_value(mapping, 'num_flats', 'numberofflats', 'flats')

        if not name:
            name = property_ref or f'imported-property-{row_index}'
        if not address:
            if district:
                address = f"Bwari, {district}"
            else:
                address = f"Bwari, imported property {row_index}"
        if not property_ref:
            property_ref = str(name).strip()

        if not latitude and not longitude and not property_ref:
            continue

        prop_type_value = str(property_type).strip().lower() if property_type else ''
        if prop_type_value in ('residential', 'residentialproperty'):
            prop_type = 'residential'
        elif prop_type_value in ('commercial', 'commercialproperty'):
            prop_type = 'commercial'
        elif prop_type_value in ('industrial', 'industrialproperty'):
            prop_type = 'industrial'
        elif prop_type_value in ('land', 'plot', 'landproperty'):
            prop_type = 'land'
        else:
            prop_type = 'land' if (latitude or longitude or property_ref) else 'residential'

        latitude_value = normalize_coordinate(latitude)
        longitude_value = normalize_coordinate(longitude)
        normalized_address = str(address).strip()
        normalized_district = (str(district).strip() or 'bwari').lower()
        property_key = (
            str(name).strip().lower(),
            normalized_address.lower(),
            normalized_district,
            str(latitude_value) if latitude_value is not None else '',
            str(longitude_value) if longitude_value is not None else '',
        )
        if property_key in existing_property_signatures:
            continue
        existing_property_signatures.add(property_key)

        base_name = str(name).strip() or f'imported-property-{row_index}'
        password_index = len(valid_rows) % len(DUMMY_PROPERTY_PASSWORDS)
        username, email, password = generate_dummy_property_credentials(property_ref or base_name, password_index=password_index)
        while username in seen_usernames:
            password_index = (password_index + 1) % len(DUMMY_PROPERTY_PASSWORDS)
            username, email, password = generate_dummy_property_credentials(
                f'{property_ref or base_name}-{uuid.uuid4().hex[:4]}',
                password_index=password_index,
            )
        seen_usernames.add(username)

        valid_rows.append({
            'username': username,
            'email': email,
            'password': password,
            'property_name': str(name).strip(),
            'address': normalized_address,
            'district': normalized_district,
            'property_type': prop_type,
            'num_units': int(num_units) if str(num_units).strip() else 1,
            'num_flats': int(num_flats) if str(num_flats).strip() else 0,
            'latitude': latitude_value,
            'longitude': longitude_value,
            'notes': '',
        })

        if progress_callback and (row_index % 2000 == 0 or row_index == total_rows):
            progress(row_index, total_rows, len(valid_rows), 'Scanning valid property rows...')

    if not valid_rows:
        return 0, []

    created_rows = []
    property_batch = []
    user_batch = []

    # Hashing a password (PBKDF2) is deliberately expensive (~hundreds of ms
    # per call). Every imported row uses the same dummy password, so hash it
    # once per distinct password instead of once per row — with 100k+ rows,
    # re-hashing per row can take hours and is what was timing out the
    # import request in production.
    password_hash_cache = {}

    def hashed_password_for(raw_password):
        if raw_password not in password_hash_cache:
            password_hash_cache[raw_password] = make_password(raw_password)
        return password_hash_cache[raw_password]

    for row in valid_rows:
        raw_name = re.sub(r'[^a-zA-Z0-9 ]+', ' ', str(row['property_name']).strip())
        display_name = raw_name[:30].strip() or 'Property'
        first_name = display_name.split()[0] if display_name else 'Property'
        last_name = ' '.join(display_name.split()[1:])[:25] if len(display_name.split()) > 1 else 'Owner'
        raw_password = str(row.get('password') or '').strip()
        if not raw_password:
            raw_password = '12345678'
        user_batch.append(
            User(
                username=row['username'],
                email=row['email'],
                password=hashed_password_for(raw_password),
                first_name=first_name,
                last_name=last_name,
            )
        )

    created_users = []
    for index in range(0, len(user_batch), 1000):
        batch = user_batch[index:index + 1000]
        with transaction.atomic():
            User.objects.bulk_create(batch, batch_size=1000)
        # PostgreSQL + Django populate `.id` on each object after bulk_create,
        # so we can read ids straight off `batch` instead of re-querying the
        # database for them — this halves the round trips to Neon for this step.
        created_users.extend((user.id, user.username) for user in batch)
        if progress_callback:
            progress(min(index + len(batch), len(valid_rows)), len(valid_rows), len(created_users), 'Creating property accounts...')

    user_map = {username: user_id for user_id, username in created_users}
    profile_objects = []
    for row in valid_rows:
        profile_objects.append(
            UserProfile(
                user_id=user_map[row['username']],
                user_type='landlord',
                email_verified=True,
            )
        )

    for index in range(0, len(profile_objects), 1000):
        chunk = profile_objects[index:index + 1000]
        with transaction.atomic():
            UserProfile.objects.bulk_create(chunk, batch_size=1000)

    for row in valid_rows:
        property_batch.append(
            Property(
                owner_id=user_map[row['username']],
                name=row['property_name'],
                address=row['address'],
                district=row['district'],
                property_type=row['property_type'],
                num_units=row['num_units'],
                num_flats=row['num_flats'],
                latitude=row['latitude'],
                longitude=row['longitude'],
                nearest_community='',
                property_level='',
                notes=row['notes'],
            )
        )

    for index in range(0, len(property_batch), 1000):
        chunk = property_batch[index:index + 1000]
        with transaction.atomic():
            Property.objects.bulk_create(chunk, batch_size=1000)
        if progress_callback:
            progress(min(index + len(chunk), len(valid_rows)), len(valid_rows), len(created_users), 'Saving properties...')

    created_rows = [{
        'property_name': row['property_name'],
        'username': row['username'],
        'email': row['email'],
        'password': row['password'],
        'property_id': (
            Property.objects.filter(owner__username=row['username'], name=row['property_name'])
            .order_by('-id').values_list('id', flat=True).first()
        ),
    } for row in valid_rows[:max_preview_rows]]

    if progress_callback:
        progress(len(valid_rows), len(valid_rows), len(valid_rows), 'Import complete.')

    return len(valid_rows), created_rows


def send_forgot_password_email(user, otp_code):
    subject = 'Password Reset – Bwari Tenement System'
    message = (
        f"Hello {user.first_name or user.username},\n\n"
        f"We received a request to reset your password.\n\n"
        f"Your verification code is:\n\n"
        f"    {otp_code}\n\n"
        f"It expires in 10 minutes. If you didn't request this, ignore this email."
    )
    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )
        return True
    except Exception as e:
        print(f"Forgot password email error: {e}")
        return False


# ── Bot-protection helpers ────────────────────────────────────────────────────

def _get_client_ip(request):
    """Return the real client IP, honouring X-Forwarded-For if behind a proxy."""
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '0.0.0.0')


def _is_rate_limited(key, limit, window_seconds):
    """
    Simple cache-based rate limiter.
    Returns True if the caller has exceeded `limit` attempts within
    `window_seconds`. Uses Django's cache backend (no extra packages needed).
    """
    count = cache.get(key, 0)
    if count >= limit:
        return True
    # increment; set TTL only on the first hit so the window slides correctly
    if count == 0:
        cache.set(key, 1, window_seconds)
    else:
        cache.incr(key)
    return False


def _purge_stale_unverified_accounts():
    """
    Delete unverified accounts that are more than 24 hours old.
    Called automatically after each successful signup so the table stays clean
    without needing a separate cron job (though the management command is
    still useful for one-off cleanups).
    """
    cutoff = timezone.now() - timedelta(hours=24)
    User.objects.filter(
        userprofile__email_verified=False,
        date_joined__lt=cutoff,
    ).delete()

def csrf_failure(request, reason=""):
    """
    Custom CSRF failure view that redirects to the signup page with an error message.
    """
    messages.error(request, 'Security check failed. Please try submitting the form again.')
    return redirect('signup')

# ── Public pages ──────────────────────────────────────────────────────────────
def home(request):
    return render(request, 'home.html')

def about(request):
    return render(request, 'about.html')

def sanitation(request):
    return render(request, 'sanitation.html')

def contact(request):
    return render(request, 'contact.html')


# ── Auth ──────────────────────────────────────────────────────────────────────
def signup_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    ip = _get_client_ip(request)

    if request.method == 'POST':
        # ── Rate limit: max 5 signup attempts per IP per hour ─────────────────
        rl_key = f'signup_attempts:{ip}'
        if _is_rate_limited(rl_key, limit=5, window_seconds=3600):
            messages.error(
                request,
                'Too many registration attempts from your connection. '
                'Please try again in an hour.'
            )
            return render(request, 'auth/signup.html', {'form': SignupForm()})

        form = SignupForm(request.POST)
        if form.is_valid():
            # ── Honeypot: reject silently if the hidden field was filled ──────
            if form.cleaned_data.get('website'):
                messages.error(request, 'Invalid submission.')
                return redirect('signup')

            user = form.save()

            # Log them in immediately
            login(request, user)

            # Generate OTP and send verification email
            otp = OTP.create_otp(user)
            if send_otp_email(user, otp.code):
                # Clean up old bot/stale accounts on each real signup
                _purge_stale_unverified_accounts()
                messages.success(request, 'Account created! Check your email for the verification code.')
                return redirect('verify_email')
            else:
                messages.error(request, 'Could not send verification email. Please try again later.')
                otp.delete()
                return redirect('signup')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = SignupForm()

    return render(request, 'auth/signup.html', {'form': form})

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    ip = _get_client_ip(request)

    if request.method == 'POST':
        # ── Rate limit: max 10 login attempts per IP per 15 minutes ──────────
        rl_key = f'login_attempts:{ip}'
        if _is_rate_limited(rl_key, limit=10, window_seconds=900):
            messages.error(
                request,
                'Too many login attempts. Please wait 15 minutes before trying again.'
            )
            return render(request, 'auth/login.html', {'form': LoginForm()})

        form = LoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']
            remember = form.cleaned_data.get('remember_me', False)

            user = authenticate(request, username=username, password=password)
            if user is not None:
                login(request, user)
                if not remember:
                    request.session.set_expiry(0)
                messages.success(request, f"Welcome back, {user.username}!")
                return redirect('dashboard')
            else:
                messages.error(request, "Invalid username or password.")
    else:
        form = LoginForm()

    return render(request, 'auth/login.html', {'form': form})


@login_required
def logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect('home')


# ── Email Verification views ──────────────────────────────────────────────────
@login_required
def verify_email(request):
    profile = request.user.userprofile
    if profile.email_verified:
        messages.info(request, 'Your email is already verified.')
        return redirect('dashboard')

    try:
        user_otp = OTP.objects.get(user=request.user)
    except OTP.DoesNotExist:
        # Create a new OTP and send email
        otp = OTP.create_otp(request.user)
        send_otp_email(request.user, otp.code)
        messages.info(request, 'A new verification code has been sent to your email.')
        return redirect('verify_email')

    if request.method == 'POST':
        form = OTPVerificationForm(request.POST)
        if form.is_valid():
            code = form.cleaned_data['otp_code']
            if not user_otp.is_valid():
                messages.error(request, 'OTP expired. A new one has been sent.')
                OTP.create_otp(request.user)
                send_otp_email(request.user, OTP.objects.get(user=request.user).code)
                return redirect('verify_email')

            if user_otp.verify(code):
                profile.email_verified = True
                profile.save(update_fields=['email_verified'])
                messages.success(request, 'Email verified! Welcome to the Bwari Tenement System.')
                return redirect('dashboard')
            else:
                messages.error(request, 'Invalid code. Please try again.')
    else:
        form = OTPVerificationForm()

    return render(request, 'auth/verify_email.html', {
        'form': form,
        'user_email': request.user.email,
    })


@login_required
def resend_otp(request):
    user = request.user
    ip   = _get_client_ip(request)

    # Max 3 resend requests per user per 10 minutes
    rl_key = f'resend_otp:{user.pk}:{ip}'
    if _is_rate_limited(rl_key, limit=3, window_seconds=600):
        messages.error(request, 'Too many resend requests. Please wait a few minutes.')
        return redirect('verify_email')

    otp = OTP.create_otp(user)
    if send_otp_email(user, otp.code):
        messages.success(request, f'A new code was sent to {user.email}.')
    else:
        messages.error(request, 'Failed to send email. Please try again.')
    return redirect('verify_email')


# ── Dashboard ─────────────────────────────────────────────────────────────────
@login_required
@verified_email_required
def dashboard(request):
    profile = request.user.userprofile
    context = {'user_type': profile.user_type}

    if profile.user_type in ['admin', 'staff', 'field_staff']:
        residential_count = Property.objects.filter(property_type='residential').count()
        commercial_count = Property.objects.filter(property_type='commercial').count()
        industrial_count = Property.objects.filter(property_type='industrial').count()
        land_count = Property.objects.filter(property_type='land').count()

        # Sanitation payer counts — mirror the exact logic used in
        # admin_sanitation_defaulters so the dashboard numbers always match
        # the Sanitation Records page (per-user × per-rate records).
        #
        # NOTE: this used to issue one .exists() query per (landlord, rate)
        # pair in a Python loop. That was fine with a handful of landlords,
        # but with 100k+ imported landlord accounts it meant 100k+ synchronous
        # database round trips on every dashboard load — which is what was
        # timing out the whole page. Replaced with a handful of bulk queries
        # that compute the same per-(user, rate) paid/unpaid counts.
        now = timezone.now()
        sanitation_rates = list(PaymentRate.objects.filter(is_sanitation=True, is_active=True))
        eligible_user_ids = list(User.objects.filter(
            userprofile__user_type='landlord',
            userprofile__email_verified=True,
        ).values_list('id', flat=True))

        total_pairs = len(eligible_user_ids) * len(sanitation_rates)
        _san_paid = 0
        if eligible_user_ids and sanitation_rates:
            for _rate in sanitation_rates:
                paid_landlord_ids = Payment.objects.filter(
                    landlord_id__in=eligible_user_ids,
                    payment_rate=_rate,
                    status='success',
                    property=None,
                ).filter(
                    django_models.Q(expires_at__isnull=True) | django_models.Q(expires_at__gt=now)
                ).values_list('landlord_id', flat=True).distinct()
                _san_paid += len(set(paid_landlord_ids))
        _san_unpaid = total_pairs - _san_paid

        sanitation_payers_count   = _san_paid
        sanitation_non_payers_count = _san_unpaid
        total_sanitation_eligible = _san_paid + _san_unpaid

        context.update({
            'residential_count': residential_count,
            'commercial_count': commercial_count,
            'industrial_count': industrial_count,
            'land_count': land_count,
            'total_users':               UserProfile.objects.filter(email_verified=True).count(),
            'total_landlords':           UserProfile.objects.filter(user_type='landlord', email_verified=True).count(),
            'total_properties':          Property.objects.count(),
            'open_complaints':           Complaint.objects.filter(status='open').count(),
            'sanitation_payers_count':   sanitation_payers_count,
            'sanitation_non_payers_count': sanitation_non_payers_count,
            'total_sanitation_eligible': total_sanitation_eligible,
        })
    elif profile.user_type == 'landlord':
        properties = Property.objects.filter(owner=request.user).order_by('-created_at')
        my_complaints = Complaint.objects.filter(submitted_by=request.user)
        properties_with_status = []
        for prop in properties:
            prop.paid = is_property_fully_paid(prop)
            properties_with_status.append(prop)

        total_paid = Payment.objects.filter(landlord=request.user, status='success').aggregate(total=Sum('amount'))['total'] or 0

        outstanding_bills = 0
        obligations_list = []
        paid_coverage_list = []
        for prop in properties:
            for rate in PaymentRate.objects.filter(property_type=prop.property_type, is_active=True):
                valid_payment = get_latest_valid_payment(prop, rate)
                if valid_payment:
                    paid_coverage_list.append({'property': prop, 'rate': rate, 'payment': valid_payment})
                else:
                    if rate.is_per_unit and prop.property_type == 'residential' and prop.num_flats > 0:
                        computed_amount = rate.amount * prop.num_flats
                    else:
                        computed_amount = rate.amount
                    outstanding_bills += computed_amount
                    obligations_list.append({
                        'property': prop,
                        'rate': rate,
                        'computed_amount': computed_amount,
                    })

        # Include sanitation levy obligations for landlords as well
        sanitation_rates = PaymentRate.objects.filter(is_sanitation=True, is_active=True)
        for rate in sanitation_rates:
            valid_payment = Payment.objects.filter(
                landlord=request.user,
                payment_rate=rate,
                property=None,
                status='success',
            ).filter(
                django_models.Q(expires_at__isnull=True) | django_models.Q(expires_at__gt=timezone.now())
            ).first()
            if valid_payment:
                paid_coverage_list.append({'property': None, 'rate': rate, 'payment': valid_payment})
            else:
                outstanding_bills += rate.amount
                obligations_list.append({
                    'property': None,
                    'rate': rate,
                    'computed_amount': rate.amount,
                })

        context.update({
            'properties': properties_with_status,
            'total_properties': len(properties_with_status),
            'total_paid': total_paid,
            'outstanding_bills': outstanding_bills,
            'obligations_list': obligations_list,
            'paid_coverage_list': paid_coverage_list,
            'total_complaints': my_complaints.count(),
            'open_complaints': my_complaints.filter(status='open').count(),
        })

    return render(request, 'dashboard.html', context)


# ── Profile ───────────────────────────────────────────────────────────────────
@login_required
@verified_email_required
def profile_view(request):
    profile = request.user.userprofile
    if request.method == 'POST':
        form = ProfileUpdateForm(request.POST, instance=profile, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated successfully.")
            return redirect('profile')
    else:
        form = ProfileUpdateForm(instance=profile, user=request.user)

    return render(request, 'profile.html', {'form': form, 'user_type': profile.user_type})


# ── Properties (landlord) ─────────────────────────────────────────────────────
@login_required
@verified_email_required
def register_property(request):
    profile = request.user.userprofile
    if profile.user_type not in ['landlord', 'staff', 'field_staff']:
        messages.error(request, "Only landlords, staff, and field staff can register properties.")
        return redirect('dashboard')

    if request.method == 'POST':
        form = PropertyRegistrationForm(request.POST, request.FILES)
        if form.is_valid():
            prop = form.save(owner=request.user)
            messages.success(request, f'Property "{prop.name}" registered successfully!')
            return redirect('dashboard')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = PropertyRegistrationForm()

    return render(request, 'register_property.html', {'form': form})


def view_property(request, property_id):
    property_obj = get_object_or_404(Property, id=property_id)
    if not user_can_manage_property(request.user, property_obj):
        messages.error(request, 'You do not have permission to view this property.')
        return redirect('dashboard')
    context = {
        'property': property_obj,
        'property_payment_status': get_property_payment_status(property_obj),
        'is_fully_paid': is_property_fully_paid(property_obj),
        'sanitation_paid': is_property_sanitation_paid(property_obj),
        'sanitation_status': get_property_sanitation_status(property_obj),
        'owner': property_obj.owner,
        'can_manage': user_can_manage_property(request.user, property_obj),
    }
    return render(request, 'view_property.html', context)


@login_required
@verified_email_required
def edit_property(request, property_id):
    property_obj = get_object_or_404(Property, id=property_id)
    if not user_can_manage_property(request.user, property_obj):
        messages.error(request, 'You do not have permission to edit this property.')
        return redirect('dashboard')

    if request.method == 'POST':
        form = PropertyEditForm(request.POST, request.FILES, property_obj=property_obj)
        if form.is_valid():
            form.save(property_obj)
            messages.success(request, f'Property "{property_obj.name}" updated successfully.')
            return redirect('view_property', property_id=property_obj.id)
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = PropertyEditForm(
            initial={
                'name': property_obj.name,
                'address': property_obj.address,
                'district': property_obj.district,
                'property_type': property_obj.property_type,
                'num_units': property_obj.num_units,
                'num_flats': property_obj.num_flats,
                'latitude': property_obj.latitude,
                'longitude': property_obj.longitude,
                'notes': property_obj.notes,
            },
            property_obj=property_obj,
        )

    return render(request, 'edit_property.html', {'form': form, 'property': property_obj})


@login_required
@verified_email_required
def delete_property(request, property_id):
    property_obj = get_object_or_404(Property, id=property_id)
    if not user_can_manage_property(request.user, property_obj):
        messages.error(request, 'You do not have permission to delete this property.')
        return redirect('dashboard')
    name = property_obj.name
    property_obj.delete()
    messages.success(request, f'Property "{name}" deleted successfully.')
    return redirect('landlord_properties')


@login_required
@verified_email_required
def landlord_properties(request):
    profile = request.user.userprofile
    if profile.user_type != 'landlord':
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    properties = Property.objects.filter(owner=request.user).order_by('-created_at')

    search = request.GET.get('search', '').strip()
    if search:
        properties = properties.filter(
            Q(name__icontains=search) | Q(address__icontains=search)
        )

    prop_type = request.GET.get('property_type', '')
    if prop_type in ('residential', 'commercial', 'industrial', 'land'):
        properties = properties.filter(property_type=prop_type)

    district = request.GET.get('district', '')
    if district:
        properties = properties.filter(district=district)

    paginator = Paginator(properties, 9)
    page_number = request.GET.get('page')
    properties_page = paginator.get_page(page_number)

    for prop in properties_page:
        prop.paid = is_property_fully_paid(prop)

    context = {
        'properties':   properties_page,
        'total':        Property.objects.filter(owner=request.user).count(),
        'search':       search,
        'prop_type':    prop_type,
        'district':     district,
    }
    return render(request, 'landlord/my_properties.html', context)


# ── Complaints (landlord) ─────────────────────────────────────────────────────
@login_required
@verified_email_required
def submit_complaint(request):
    profile = request.user.userprofile
    if profile.user_type != 'landlord':
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    if request.method == 'POST':
        form = ComplaintForm(request.POST)
        if form.is_valid():
            complaint = form.save(commit=False)
            complaint.submitted_by = request.user
            complaint.save()
            messages.success(request, "Your complaint has been submitted. An admin will review it shortly.")
            return redirect('my_complaints')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = ComplaintForm()

    return render(request, 'landlord/submit_complaint.html', {'form': form})


@login_required
@verified_email_required
def my_complaints(request):
    profile = request.user.userprofile
    if profile.user_type != 'landlord':
        return redirect('dashboard')

    complaints = Complaint.objects.filter(submitted_by=request.user)
    return render(request, 'landlord/my_complaints.html', {'complaints': complaints})


# ── Admin: Users ──────────────────────────────────────────────────────────────
@staff_member_required
def admin_manage_users(request):
    users = User.objects.select_related('userprofile').filter(userprofile__email_verified=True).order_by('id')

    user_type = request.GET.get('user_type')
    if user_type:
        users = users.filter(userprofile__user_type=user_type)

    status = request.GET.get('status')
    if status == 'active':
        users = users.filter(is_active=True)
    elif status == 'inactive':
        users = users.filter(is_active=False)

    search = request.GET.get('search')
    if search:
        users = users.filter(
            Q(username__icontains=search) |
            Q(email__icontains=search) |
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search)
        )

    paginator = Paginator(users, 20)
    page_number = request.GET.get('page')
    users_page = paginator.get_page(page_number)
    users_page_range = get_paginator_page_range(users_page)

    context = {
        'users':            users_page,
        'page_range':       users_page_range,
        'total_users':      UserProfile.objects.filter(email_verified=True).count(),
        'total_landlords':  UserProfile.objects.filter(user_type='landlord', email_verified=True).count(),
        'total_admins':     UserProfile.objects.filter(user_type='admin', email_verified=True).count(),
        'total_staff':      UserProfile.objects.filter(user_type='staff', email_verified=True).count(),
        'total_field_staff': UserProfile.objects.filter(user_type='field_staff', email_verified=True).count(),
    }
    return render(request, 'admin/manage_users.html', context)


@staff_member_required
def admin_reset_demo_data(request):
    profile = request.user.userprofile
    if profile.user_type != 'admin':
        messages.error(request, 'Only admins can reset the demo database.')
        return redirect('dashboard')

    if request.method == 'POST':
        property_count = Property.objects.count()
        protected_user_ids = list(
            User.objects.filter(userprofile__user_type='admin').values_list('id', flat=True)
        )

        Property.objects.all().delete()
        User.objects.exclude(id__in=protected_user_ids).delete()

        messages.success(request, f'Reset complete: {property_count} properties deleted and all non-admin accounts removed.')
    return redirect('admin_manage_users')


@staff_member_required
def admin_view_user(request, user_id):
    user_obj = get_object_or_404(User.objects.select_related('userprofile'), id=user_id)
    properties = Property.objects.filter(owner=user_obj)
    complaints = Complaint.objects.filter(submitted_by=user_obj)
    context = {
        'user_obj':   user_obj,
        'profile':    user_obj.userprofile,
        'properties': properties,
        'complaints': complaints,
    }
    return render(request, 'admin/view_user.html', context)


@staff_member_required
def admin_delete_user(request, user_id):
    user_obj = get_object_or_404(User, id=user_id)
    if user_obj != request.user:
        username = user_obj.username
        user_obj.delete()
        messages.success(request, f'User "{username}" deleted successfully.')
    else:
        messages.error(request, 'You cannot delete your own account.')
    return redirect('admin_manage_users')


# ── Admin: Properties ─────────────────────────────────────────────────────────
@staff_or_admin_required
def admin_manage_properties(request):
    from .forms import DISTRICT_CHOICES
    properties = Property.objects.select_related('owner').all()

    prop_type = request.GET.get('property_type')
    if prop_type in ('residential', 'commercial', 'industrial', 'land'):
        properties = properties.filter(property_type=prop_type)

    district = request.GET.get('district')
    if district:
        properties = properties.filter(district=district)

    search = request.GET.get('search')
    if search:
        properties = properties.filter(
            Q(name__icontains=search) |
            Q(address__icontains=search) |
            Q(owner__username__icontains=search)
        )

    paid_status = request.GET.get('paid_status', '')
    props_list = list(properties)
    if paid_status == 'paid':
        props_list = [p for p in props_list if is_property_fully_paid(p)]
    elif paid_status == 'unpaid':
        props_list = [p for p in props_list if not is_property_fully_paid(p)]

    total_properties  = Property.objects.count()
    residential_count = Property.objects.filter(property_type='residential').count()
    commercial_count  = Property.objects.filter(property_type='commercial').count()
    industrial_count  = Property.objects.filter(property_type='industrial').count()
    land_count        = Property.objects.filter(property_type='land').count()

    district_counts = {
        val: Property.objects.filter(district=val).count()
        for val, _ in DISTRICT_CHOICES
    }

    paginator = Paginator(props_list, 12)
    page_number = request.GET.get('page')
    properties_page = paginator.get_page(page_number)
    properties_page_range = get_paginator_page_range(properties_page)

    for prop in properties_page:
        prop.payment_status = get_property_payment_status(prop)
        prop.paid = prop.payment_status == 'paid'
        prop.sanitation_status = get_property_sanitation_status(prop)
        prop.sanitation_paid = prop.sanitation_status == 'paid'

    context = {
        'properties':        properties_page,
        'page_range':       properties_page_range,
        'total_properties':  total_properties,
        'residential_count': residential_count,
        'commercial_count':  commercial_count,
        'industrial_count':  industrial_count,
        'land_count':        land_count,
        'district_choices':  DISTRICT_CHOICES,
        'district_counts':   district_counts,
        'paid_status':       paid_status,
    }
    return render(request, 'admin/manage_properties.html', context)


@staff_or_admin_required
def admin_view_property(request, property_id):
    property_obj = get_object_or_404(Property, id=property_id)
    context = {
        'property': property_obj,
        'property_payment_status': get_property_payment_status(property_obj),
        'is_fully_paid': is_property_fully_paid(property_obj),
        'sanitation_paid': is_property_sanitation_paid(property_obj),
        'sanitation_status': get_property_sanitation_status(property_obj),
    }
    return render(request, 'admin/view_property.html', context)


@staff_or_admin_required
def admin_delete_property(request, property_id):
    property_obj = get_object_or_404(Property, id=property_id)
    name = property_obj.name
    property_obj.delete()
    messages.success(request, f'Property "{name}" deleted successfully.')
    return redirect('admin_manage_properties')


# ── Admin: Complaints ─────────────────────────────────────────────────────────
@staff_member_required
def admin_manage_complaints(request):
    complaints = Complaint.objects.select_related('submitted_by').all()

    status_filter = request.GET.get('status', '')
    if status_filter:
        complaints = complaints.filter(status=status_filter)

    category_filter = request.GET.get('category', '')
    if category_filter:
        complaints = complaints.filter(category=category_filter)

    search = request.GET.get('search', '').strip()
    if search:
        complaints = complaints.filter(
            Q(subject__icontains=search) |
            Q(submitted_by__username__icontains=search) |
            Q(submitted_by__first_name__icontains=search) |
            Q(submitted_by__last_name__icontains=search)
        )

    total_complaints    = Complaint.objects.count()
    open_count          = Complaint.objects.filter(status='open').count()
    in_review_count     = Complaint.objects.filter(status='in_review').count()
    resolved_count      = Complaint.objects.filter(status='resolved').count()

    paginator = Paginator(complaints, 15)
    page_number = request.GET.get('page')
    complaints_page = paginator.get_page(page_number)

    from .models import COMPLAINT_STATUS_CHOICES, COMPLAINT_CATEGORY_CHOICES

    context = {
        'complaints':        complaints_page,
        'total_complaints':  total_complaints,
        'open_count':        open_count,
        'in_review_count':   in_review_count,
        'resolved_count':    resolved_count,
        'status_choices':    COMPLAINT_STATUS_CHOICES,
        'category_choices':  COMPLAINT_CATEGORY_CHOICES,
        'status_filter':     status_filter,
        'category_filter':   category_filter,
        'search':            search,
    }
    return render(request, 'admin/manage_complaints.html', context)


@staff_member_required
def admin_view_complaint(request, complaint_id):
    complaint = get_object_or_404(Complaint, id=complaint_id)

    if request.method == 'POST':
        form = AdminComplaintUpdateForm(request.POST, instance=complaint)
        if form.is_valid():
            form.save()
            messages.success(request, "Complaint updated successfully.")
            return redirect('admin_view_complaint', complaint_id=complaint_id)
    else:
        form = AdminComplaintUpdateForm(instance=complaint)

    return render(request, 'admin/view_complaint.html', {
        'complaint': complaint,
        'form':      form,
    })


# ── Admin: Site Configuration ─────────────────────────────────────────────────
@staff_member_required
def admin_site_configuration(request):
    config = SiteConfiguration.get_config()

    if request.method == 'POST':
        form = SiteConfigurationForm(request.POST, instance=config)
        if form.is_valid():
            cfg = form.save(commit=False)
            cfg.updated_by = request.user
            cfg.save()
            messages.success(request, "Site configuration saved successfully.")
            return redirect('admin_site_configuration')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = SiteConfigurationForm(instance=config)

    return render(request, 'admin/site_configuration.html', {
        'form':   form,
        'config': config,
    })


# ── Admin: Export Data ────────────────────────────────────────────────────────
@staff_member_required
def admin_export_landlords(request):
    """Kept for backward-compat — redirects to the unified user export."""
    return admin_export_users(request)


@staff_member_required
def admin_export_users(request):
    """Export all non-admin, non-staff user accounts (landlords, tenants, etc.)."""
    user_profiles = (
        UserProfile.objects
        .exclude(user_type__in=['admin', 'staff', 'field_staff'])
        .select_related('user')
        .order_by('user__date_joined')
    )

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "User Directory"

    header_fill  = PatternFill("solid", fgColor="1E6CF0")
    header_font  = Font(bold=True, color="FFFFFF", name="Calibri", size=11)
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    title_font   = Font(bold=True, name="Calibri", size=14, color="0F1117")
    sub_font     = Font(name="Calibri", size=10, color="6B7280")
    cell_align   = Alignment(vertical="center")
    alt_fill     = PatternFill("solid", fgColor="F7F8FA")
    thin_border  = Border(
        left=Side(style='thin', color='E5E7EB'),
        right=Side(style='thin', color='E5E7EB'),
        top=Side(style='thin', color='E5E7EB'),
        bottom=Side(style='thin', color='E5E7EB'),
    )

    # Title row
    ws.merge_cells('A1:K1')
    title_cell = ws['A1']
    title_cell.value = "Bwari Tenement System — User Directory"
    title_cell.font  = title_font
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 30

    # Subtitle row
    ws.merge_cells('A2:K2')
    sub_cell = ws['A2']
    sub_cell.value = f"Exported on {timezone.now().strftime('%d %B %Y at %H:%M')} UTC  |  Excludes admin & staff accounts"
    sub_cell.font  = sub_font
    sub_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[2].height = 18
    ws.row_dimensions[3].height = 8  # spacer

    HEADERS = [
        ('#',               8),
        ('Username',        18),
        ('First Name',      18),
        ('Last Name',       18),
        ('Email',           30),
        ('User Type',       14),
        ('Phone Number',    18),
        ('Address',         30),
        ('Account Status',  16),
        ('Properties',      14),
        ('Date Joined',     20),
    ]

    for col_idx, (header, width) in enumerate(HEADERS, start=1):
        cell = ws.cell(row=4, column=col_idx, value=header)
        cell.font      = header_font
        cell.fill      = header_fill
        cell.alignment = header_align
        cell.border    = thin_border
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    ws.row_dimensions[4].height = 22

    # User-type colour map for the "User Type" column
    TYPE_COLORS = {
        'landlord': '15803D',   # green
        'tenant':   '1558C8',   # blue
    }

    for row_num, profile in enumerate(user_profiles, start=1):
        u         = profile.user
        excel_row = row_num + 4
        row_fill  = alt_fill if row_num % 2 == 0 else None
        prop_count = u.properties.count() if hasattr(u, 'properties') else 0

        row_data = [
            row_num,
            u.username,
            u.first_name,
            u.last_name,
            u.email,
            profile.get_user_type_display(),
            profile.phone_number or '—',
            profile.address or '—',
            'Active' if u.is_active else 'Inactive',
            prop_count,
            u.date_joined.strftime('%d %b %Y %H:%M'),
        ]

        for col_idx, value in enumerate(row_data, start=1):
            cell = ws.cell(row=excel_row, column=col_idx, value=value)
            cell.border    = thin_border
            cell.alignment = cell_align
            if row_fill:
                cell.fill = row_fill
            # Colour-code "User Type" column (col 6)
            if col_idx == 6:
                color = TYPE_COLORS.get(profile.user_type, '3B3F4A')
                cell.font = Font(color=color, bold=True, name="Calibri")
            # Colour-code "Account Status" column (col 9)
            if col_idx == 9:
                if value == 'Active':
                    cell.font = Font(color="16A34A", bold=True, name="Calibri")
                else:
                    cell.font = Font(color="DC2626", bold=True, name="Calibri")

        ws.row_dimensions[excel_row].height = 18

    # Summary footer
    summary_row = user_profiles.count() + 5
    ws.merge_cells(f'A{summary_row}:I{summary_row}')
    summary_cell = ws[f'A{summary_row}']
    summary_cell.value = (
        f"Total users exported: {user_profiles.count()}  |  "
        f"Landlords: {user_profiles.filter(user_type='landlord').count()}  |  "
        f"Tenants: {user_profiles.filter(user_type='tenant').count()}"
    )
    summary_cell.font      = Font(bold=True, name="Calibri", size=10, color="1E6CF0")
    summary_cell.alignment = Alignment(horizontal="right", vertical="center")

    ws.freeze_panes = 'A5'

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    filename = f"users_{timezone.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    response = HttpResponse(
        buffer.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def page_not_found(request, exception=None):
    return render(request, '404.html', {'request': request}, status=404)

@staff_member_required
def admin_sanitation_defaulters(request):
    profile = request.user.userprofile
    if profile.user_type not in ['admin', 'staff', 'field_staff']:
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    sanitation_rates = list(PaymentRate.objects.filter(is_sanitation=True, is_active=True))
    all_records = []
    now = timezone.now()

    # All users (landlords + tenants) are subject to sanitation levy
    users = list(User.objects.filter(
        userprofile__user_type__in=['landlord', 'tenant'],
        userprofile__email_verified=True,
    ).select_related('userprofile'))

    # NOTE: this used to run one Payment query per (user, rate) pair — with
    # 100k+ imported accounts that's 100k+ synchronous DB round trips and
    # crashes the page. Instead, pull every relevant "latest valid payment"
    # in a constant number of queries and look them up from memory.
    user_ids = [u.id for u in users]
    latest_valid_payment_by_pair = {}
    if user_ids and sanitation_rates:
        candidate_payments = (
            Payment.objects.filter(
                landlord_id__in=user_ids,
                payment_rate__in=sanitation_rates,
                status='success',
                property=None,
            )
            .filter(django_models.Q(expires_at__isnull=True) | django_models.Q(expires_at__gt=now))
            .order_by('landlord_id', 'payment_rate_id', '-paid_at')
        )
        for payment in candidate_payments:
            key = (payment.landlord_id, payment.payment_rate_id)
            # order_by above puts each pair's most recent valid payment first;
            # keep only that first one per pair.
            if key not in latest_valid_payment_by_pair:
                latest_valid_payment_by_pair[key] = payment

    for user in users:
        for rate in sanitation_rates:
            valid_payment = latest_valid_payment_by_pair.get((user.id, rate.id))

            has_paid = valid_payment is not None
            all_records.append({
                'user': user,
                'profile': user.userprofile,
                'rate': rate,
                'amount': rate.amount,
                'has_paid': has_paid,
                'payment': valid_payment,
            })

    defaulters_count = sum(1 for r in all_records if not r['has_paid'])
    paid_count = sum(1 for r in all_records if r['has_paid'])

    return render(request, 'admin/sanitation_defaulters.html', {
        'all_records': all_records,
        'defaulters_count': defaulters_count,
        'paid_count': paid_count,
        # keep legacy 'defaulters' context for the export URL in template
        'defaulters': [r for r in all_records if not r['has_paid']],
    })

@staff_member_required
def admin_export_sanitation_defaulters(request):
    profile = request.user.userprofile
    if profile.user_type not in ['admin', 'staff', 'field_staff']:
        messages.error(request, 'Access denied.')
        return redirect('dashboard')

    export_mode = request.GET.get('mode', 'defaulters')  # 'all' or 'defaulters'
    export_all = export_mode == 'all'

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'All Sanitation Records' if export_all else 'Sanitation Defaulters'

    header_font = Font(bold=True, color='FFFFFF', size=11)
    header_fill = PatternFill('solid', fgColor='1E3A5F')
    header_align = Alignment(horizontal='center', vertical='center')
    thin = Side(border_style='thin', color='D1D5DB')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    headers = [
        'Username', 'Full Name', 'Email', 'Phone', 'Address', 'User Type',
        'Sanitation Rate', 'Amount (₦)', 'Payment Status',
        'Paid On', 'Expires On',
    ]
    widths = [18, 22, 28, 16, 36, 14, 32, 18, 16, 20, 20]

    for i, (label, width) in enumerate(zip(headers, widths), 1):
        cell = ws.cell(row=1, column=i, value=label)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = border
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.row_dimensions[1].height = 24

    sanitation_rates = PaymentRate.objects.filter(is_sanitation=True, is_active=True)
    users = User.objects.filter(userprofile__user_type__in=['landlord', 'tenant']).select_related('userprofile')
    row_num = 2
    alt_fill = PatternFill('solid', fgColor='F7F8FA')
    paid_fill = PatternFill('solid', fgColor='DCFCE7')
    now = timezone.now()

    for user in users:
        for rate in sanitation_rates:
            valid_payment = Payment.objects.filter(
                landlord=user,
                payment_rate=rate,
                status='success',
                property=None,
            ).filter(
                django_models.Q(expires_at__isnull=True) | django_models.Q(expires_at__gt=now)
            ).order_by('-paid_at').first()

            has_paid = valid_payment is not None

            if not export_all and has_paid:
                continue  # skip paid users when exporting defaulters only

            row_fill = paid_fill if has_paid else (alt_fill if row_num % 2 == 0 else PatternFill('solid', fgColor='FFFFFF'))
            row_data = [
                user.username,
                user.get_full_name() or '—',
                user.email,
                getattr(user.userprofile, 'phone_number', '') or '—',
                getattr(user.userprofile, 'address', '') or '—',
                user.userprofile.get_user_type_display(),
                rate.name,
                float(rate.amount),
                'Paid' if has_paid else 'Outstanding',
                valid_payment.paid_at.strftime('%Y-%m-%d') if has_paid and valid_payment.paid_at else '—',
                valid_payment.expires_at.strftime('%Y-%m-%d') if has_paid and valid_payment.expires_at else '—',
            ]
            for col, value in enumerate(row_data, 1):
                cell = ws.cell(row=row_num, column=col, value=value)
                cell.border = border
                cell.fill = row_fill
                cell.alignment = Alignment(vertical='center')
                if col == 8:   # Amount (₦) — now column 8
                    cell.number_format = '#,##0.00'
                if col == 9:   # Payment Status — now column 9
                    cell.font = Font(
                        bold=True,
                        color='15803D' if has_paid else 'DC2626',
                    )
            row_num += 1

    if row_num == 2:
        ws.cell(row=2, column=1, value='No records found.')

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename_prefix = 'sanitation_all_users' if export_all else 'sanitation_defaulters'
    response = HttpResponse(
        output.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename_prefix}_{timezone.now().strftime("%Y%m%d")}.xlsx"'
    return response

# ── Admin: Payment Rates ─────────────────────────────────────────────────────
@staff_member_required
def admin_fixed_rate(request):
    profile = request.user.userprofile
    if profile.user_type != 'admin':
        messages.error(request, "Only admins can manage fixed rates.")
        return redirect('dashboard')

    fixed_rates = PaymentRate.objects.filter(property_type='residential', is_per_unit=True).order_by('-created_at')

    if request.method == 'POST':
        form = FixedResidentialRateForm(request.POST)
        if form.is_valid():
            rate = form.save(commit=False)
            rate.property_type = 'residential'
            rate.is_per_unit = True
            rate.created_by = request.user
            rate.save()
            messages.success(request, f'Fixed residential rate "{rate.name}" created successfully.')
            return redirect('admin_fixed_rate')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = FixedResidentialRateForm()

    return render(request, 'admin/fixed_rate.html', {
        'form': form,
        'fixed_rates': fixed_rates,
    })


@staff_member_required
def admin_payment_rates(request):
    rates = PaymentRate.objects.all().order_by('-created_at')
    context = {'rates': rates}
    return render(request, 'admin/payment_rates.html', context)


@staff_member_required
def admin_create_payment_rate(request):
    if request.method == 'POST':
        form = PaymentRateForm(request.POST)
        if form.is_valid():
            rate = form.save(commit=False)
            rate.created_by = request.user
            rate.save()
            messages.success(request, f'Payment rate "{rate.name}" created successfully.')
            return redirect('admin_payment_rates')
    else:
        form = PaymentRateForm()
    return render(request, 'admin/create_payment_rate.html', {'form': form})


@staff_member_required
def admin_delete_payment_rate(request, rate_id):
    rate = get_object_or_404(PaymentRate, id=rate_id)
    name = rate.name
    rate.delete()
    messages.success(request, f'Payment rate "{name}" deleted.')
    return redirect('admin_payment_rates')


@staff_member_required
def admin_toggle_payment_rate(request, rate_id):
    rate = get_object_or_404(PaymentRate, id=rate_id)
    rate.is_active = not rate.is_active
    rate.save()
    status = "activated" if rate.is_active else "deactivated"
    messages.success(request, f'Payment rate "{rate.name}" {status}.')
    return redirect('admin_payment_rates')

@staff_member_required
def admin_all_payments(request):
    """Admin: full paginated payment history with search + filter."""
    qs = Payment.objects.select_related(
        'landlord', 'landlord__userprofile', 'property', 'payment_rate'
    ).order_by('-created_at')

    # ── Filters ──────────────────────────────────────────────
    q             = request.GET.get('q', '').strip()
    status        = request.GET.get('status', '').strip()
    property_type = request.GET.get('property_type', '').strip()
    date_from     = request.GET.get('date_from', '').strip()
    date_to       = request.GET.get('date_to', '').strip()

    if q:
        qs = qs.filter(
            Q(reference__icontains=q) |
            Q(landlord__username__icontains=q) |
            Q(landlord__first_name__icontains=q) |
            Q(landlord__last_name__icontains=q) |
            Q(landlord__email__icontains=q) |
            Q(property__name__icontains=q)
        )
    if status:
        qs = qs.filter(status=status)
    if property_type:
        qs = qs.filter(property__property_type=property_type)
    if date_from:
        qs = qs.filter(paid_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(paid_at__date__lte=date_to)

    # ── Summary counts (always on the full unfiltered set) ───
    all_payments    = Payment.objects.all()
    success_count   = all_payments.filter(status='success').count()
    pending_count   = all_payments.filter(status='pending').count()
    failed_count    = all_payments.filter(status='failed').count()
    total_collected = all_payments.filter(status='success').aggregate(
        total=Sum('amount')
    )['total'] or 0

    # ── Pagination ───────────────────────────────────────────
    paginator = Paginator(qs, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'admin/all_payments.html', {
        'page_obj':        page_obj,
        'success_count':   success_count,
        'pending_count':   pending_count,
        'failed_count':    failed_count,
        'total_collected': total_collected,
    })


# ── Landlord: Payments ───────────────────────────────────────────────────────
@login_required
@verified_email_required
def landlord_payments(request):
    profile = request.user.userprofile
    if profile.user_type != 'landlord':
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    properties = Property.objects.filter(owner=request.user)
    property_types = properties.values_list('property_type', flat=True).distinct()
    active_rates = PaymentRate.objects.filter(property_type__in=property_types, is_active=True)

    obligations = []
    paid_coverage = []
    for prop in properties:
        for rate in active_rates.filter(property_type=prop.property_type):
            valid_payment = get_latest_valid_payment(prop, rate)
            if valid_payment:
                paid_coverage.append({'property': prop, 'rate': rate, 'payment': valid_payment})
            else:
                if rate.is_per_unit and prop.property_type == 'residential' and prop.num_flats > 0:
                    computed_amount = rate.amount * prop.num_flats
                else:
                    computed_amount = rate.amount
                obligations.append({'property': prop, 'rate': rate, 'computed_amount': computed_amount})

    payments = Payment.objects.filter(landlord=request.user).select_related('property', 'payment_rate').order_by('-created_at')
    successful_payments_count = payments.filter(status='success').count()

    context = {
        'obligations': obligations,
        'paid_coverage': paid_coverage,
        'payments': payments,
        'successful_payments_count': successful_payments_count,
    }
    return render(request, 'landlord/payments.html', context)


# @login_required
# def initiate_payment(request, property_id, rate_id):
#     profile = request.user.userprofile
#     if profile.user_type != 'landlord':
#         messages.error(request, "Access denied.")
#         return redirect('dashboard')

#     property_obj = get_object_or_404(Property, id=property_id, owner=request.user)
#     rate = get_object_or_404(PaymentRate, id=rate_id, is_active=True)

#     if Payment.objects.filter(landlord=request.user, property=property_obj, payment_rate=rate, status='success').exists():
#         messages.info(request, "This payment has already been made.")
#         return redirect('landlord_payments')

#     if rate.is_per_unit and property_obj.property_type == 'residential' and property_obj.num_flats > 0:
#         final_amount = rate.amount * property_obj.num_flats
#     else:
#         final_amount = rate.amount

#     reference = f"BTS-{request.user.id}-{property_id}-{rate_id}-{int(timezone.now().timestamp())}"

#     payment = Payment.objects.create(
#         landlord=request.user,
#         property=property_obj,
#         payment_rate=rate,
#         amount=final_amount,
#         reference=reference,
#         status='pending'
#     )

#     paystack_url = "https://api.paystack.co/transaction/initialize"
#     headers = {
#         "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
#         "Content-Type": "application/json",
#     }
#     data = {
#         "email": request.user.email,
#         "amount": int(final_amount * 100),
#         "reference": reference,
#         "callback_url": request.build_absolute_uri(reverse('verify_payment', args=[reference])),
#         "metadata": {
#             "landlord_id": request.user.id,
#             "property_id": property_obj.id,
#             "rate_id": rate.id,
#         }
#     }

#     response = requests.post(paystack_url, headers=headers, json=data)
#     if response.status_code == 200:
#         resp_data = response.json()
#         if resp_data['status']:
#             return redirect(resp_data['data']['authorization_url'])
#         else:
#             messages.error(request, f"Payment initialization failed: {resp_data.get('message', 'Unknown error')}")
#     else:
#         messages.error(request, "Could not connect to payment gateway. Please try again later.")

#     payment.status = 'failed'
#     payment.save()
#     return redirect('landlord_payments')


@login_required
def initiate_payment(request, property_id, rate_id):
    profile = request.user.userprofile
    if profile.user_type not in ['landlord', 'tenant']:
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    rate = get_object_or_404(PaymentRate, id=rate_id, is_active=True)
    
    # Handle sanitation rate (property_id = 0)
    if property_id == 0:
        if not rate.is_sanitation:
            messages.error(request, "Invalid rate for this action.")
            return redirect('dashboard')
        property_obj = None
        # Check for existing valid payment
        existing = Payment.objects.filter(
            landlord=request.user,
            payment_rate=rate,
            status='success',
            property=None,
        ).filter(
            django_models.Q(expires_at__isnull=True) | django_models.Q(expires_at__gt=timezone.now())
        ).exists()
        if existing:
            messages.info(request, "You already have an active sanitation levy payment.")
            return redirect('tenant_payments')
    else:
        if profile.user_type != 'landlord':
            messages.error(request, "Only landlords can pay property rates.")
            return redirect('dashboard')
        property_obj = get_object_or_404(Property, id=property_id, owner=request.user)
        # Check already paid
        if Payment.objects.filter(landlord=request.user, property=property_obj, payment_rate=rate, status='success').exists():
            messages.info(request, "This payment has already been made.")
            return redirect('landlord_payments')

    reference = f"BTS-{request.user.id}-{property_id}-{rate_id}-{int(timezone.now().timestamp())}"
    payment = Payment.objects.create(
        landlord=request.user,
        property=property_obj,
        payment_rate=rate,
        amount=rate.amount,
        reference=reference,
        status='pending'
    )

    paystack_url = "https://api.paystack.co/transaction/initialize"
    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }
    data = {
        "email": request.user.email,
        "amount": int(rate.amount * 100),
        "reference": reference,
        "callback_url": request.build_absolute_uri(reverse('verify_payment', args=[reference])),
        "metadata": {
            "landlord_id": request.user.id,
            "property_id": property_id if property_obj else None,
            "rate_id": rate.id,
        }
    }

    response = requests.post(paystack_url, headers=headers, json=data)
    if response.status_code == 200:
        resp_data = response.json()
        if resp_data['status']:
            return redirect(resp_data['data']['authorization_url'])
        else:
            messages.error(request, f"Payment initialization failed: {resp_data.get('message', 'Unknown error')}")
    else:
        messages.error(request, "Could not connect to payment gateway. Please try again later.")

    payment.status = 'failed'
    payment.save()
    return redirect('tenant_payments' if property_obj is None else 'landlord_payments')


@login_required
def verify_payment(request, reference):
    payment = get_object_or_404(Payment, reference=reference, landlord=request.user)

    if payment.status == 'success':
        messages.info(request, "Payment already verified.")
        return redirect('payment_receipt', payment_id=payment.id)

    url = f"https://api.paystack.co/transaction/verify/{reference}"
    headers = {"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"}
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        resp_data = response.json()
        if resp_data['status'] and resp_data['data']['status'] == 'success':
            paid_at = timezone.now()
            validity_days = 30 if payment.payment_rate and payment.payment_rate.is_sanitation else 365
            payment.status = 'success'
            payment.paid_at = paid_at
            payment.expires_at = paid_at + timezone.timedelta(days=validity_days)
            payment.paystack_response = resp_data['data']
            payment.save()
            messages.success(request, "Payment successful! Thank you.")
            return redirect('payment_receipt', payment_id=payment.id)
        else:
            payment.status = 'failed'
            payment.paystack_response = resp_data
            payment.save()
            messages.error(request, f"Payment verification failed: {resp_data.get('message', 'Unknown error')}")
    else:
        messages.error(request, "Could not verify payment at this time. Please contact support.")

    return redirect('landlord_payments')


@login_required
def payment_receipt(request, payment_id):
    payment = get_object_or_404(Payment, id=payment_id, landlord=request.user, status='success')
    qr_data = f"Payment Ref: {payment.reference}\nAmount: ₦{payment.amount}\nProperty: {payment.property.name if payment.property else 'Environmental Sanitation Levy'}\nPaid by: {payment.landlord.get_full_name()}\nValid Until: {payment.expires_at.strftime('%d %B %Y') if payment.expires_at else 'N/A'}"
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(qr_data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    qr_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

    context = {
        'payment': payment,
        'qr_code_base64': qr_base64,
    }
    return render(request, 'landlord/receipt.html', context)


@login_required
def download_receipt_pdf(request, payment_id):
    payment = get_object_or_404(Payment, id=payment_id, landlord=request.user, status='success')
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import os

    font_path = None
    possible_paths = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/dejavu/DejaVuSans.ttf',
        'C:/Windows/Fonts/DejaVuSans.ttf',
        os.path.join(settings.BASE_DIR, 'static/fonts/DejaVuSans.ttf')
    ]
    for path in possible_paths:
        if os.path.exists(path):
            font_path = path
            break

    if font_path:
        pdfmetrics.registerFont(TTFont('DejaVu', font_path))
        title_font = 'DejaVu'
        body_font = 'DejaVu'
        naira_symbol = '₦'
    else:
        title_font = 'Helvetica-Bold'
        body_font = 'Helvetica'
        naira_symbol = 'NGN '

    p.setFont(title_font, 20)
    p.drawString(50, height - 50, "Bwari Tenement System")
    p.setFont(body_font, 12)
    p.drawString(50, height - 70, "Official Payment Receipt")
    p.line(50, height - 80, width - 50, height - 80)

    y = height - 110
    p.setFont(body_font, 12)
    p.drawString(50, y, "Receipt No:")
    p.drawString(150, y, payment.reference)

    y -= 20
    p.drawString(50, y, "Date:")
    p.drawString(150, y, payment.paid_at.strftime("%d %B %Y, %I:%M %p"))

    y -= 30
    p.setFont(title_font, 14)
    p.drawString(50, y, "Landlord Information")
    y -= 20
    p.setFont(body_font, 12)
    p.drawString(50, y, f"Name: {payment.landlord.get_full_name()}")
    y -= 20
    p.drawString(50, y, f"Email: {payment.landlord.email}")
    if payment.landlord.userprofile.phone_number:
        y -= 20
        p.drawString(50, y, f"Phone: {payment.landlord.userprofile.phone_number}")

    y -= 30
    p.setFont(title_font, 14)
    p.drawString(50, y, "Property Details")
    y -= 20
    p.setFont(body_font, 12)
    if payment.property:
        p.drawString(50, y, f"Property Name: {payment.property.name}")
        y -= 20
        p.drawString(50, y, f"Address: {payment.property.address}")
        y -= 20
        p.drawString(50, y, f"Type: {payment.property.get_property_type_display()}")
    else:
        p.drawString(50, y, "Property: Environmental Sanitation Levy")
        y -= 20
        p.drawString(50, y, "Type: Monthly Sanitation Payment")

    y -= 30
    p.setFont(title_font, 14)
    p.drawString(50, y, "Payment Details")
    y -= 20
    p.setFont(body_font, 12)
    p.drawString(50, y, f"Rate: {payment.payment_rate.name if payment.payment_rate else 'N/A'}")
    y -= 20
    amount_str = f"{naira_symbol}{payment.amount:,.2f}"
    p.drawString(50, y, f"Amount Paid: {amount_str}")
    y -= 20
    p.drawString(50, y, f"Status: {payment.get_status_display()}")
    y -= 20
    if payment.expires_at:
        p.drawString(50, y, f"Valid Until: {payment.expires_at.strftime('%d %B %Y')}")
    else:
        if payment.payment_rate and payment.payment_rate.is_sanitation:
            p.drawString(50, y, "Valid Until: 30 days from payment date")
        else:
            p.drawString(50, y, "Valid Until: 1 year from payment date")

    # QR Code
    qr_data = f"Payment Ref: {payment.reference}\nAmount: {naira_symbol}{payment.amount}\nProperty: {payment.property.name if payment.property else 'Environmental Sanitation Levy'}\nPaid by: {payment.landlord.get_full_name()}\nValid Until: {payment.expires_at.strftime('%d %B %Y') if payment.expires_at else 'N/A'}"
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(qr_data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    qr_buffer = BytesIO()
    img.save(qr_buffer, format="PNG")
    qr_buffer.seek(0)
    qr_image = ImageReader(qr_buffer)
    p.drawImage(qr_image, width - 150, height - 250, width=100, height=100)
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(qr_data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    qr_buffer = BytesIO()
    img.save(qr_buffer, format="PNG")
    qr_buffer.seek(0)
    qr_image = ImageReader(qr_buffer)
    p.drawImage(qr_image, width - 150, height - 250, width=100, height=100)

    p.showPage()
    p.save()

    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="receipt_{payment.reference}.pdf"'
    return response


@login_required
@require_GET
def get_paystack_access_code(request, property_id, rate_id):
    profile = request.user.userprofile
    if profile.user_type != 'landlord':
        return JsonResponse({'error': 'Access denied'}, status=403)

    property_obj = get_object_or_404(Property, id=property_id, owner=request.user)
    rate = get_object_or_404(PaymentRate, id=rate_id, is_active=True)

    if Payment.objects.filter(landlord=request.user, property=property_obj, payment_rate=rate, status='success').exists():
        return JsonResponse({'error': 'Already paid'}, status=400)

    reference = f"BTS-{request.user.id}-{property_id}-{rate_id}-{int(timezone.now().timestamp())}"
    payment = Payment.objects.create(
        landlord=request.user,
        property=property_obj,
        payment_rate=rate,
        amount=rate.amount,
        reference=reference,
        status='pending'
    )

    paystack_url = "https://api.paystack.co/transaction/initialize"
    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }
    data = {
        "email": request.user.email,
        "amount": int(rate.amount * 100),
        "reference": reference,
        "callback_url": request.build_absolute_uri(reverse('verify_payment', args=[reference])),
        "metadata": {
            "landlord_id": request.user.id,
            "property_id": property_obj.id,
            "rate_id": rate.id,
        }
    }

    response = requests.post(paystack_url, headers=headers, json=data)
    if response.status_code == 200:
        resp_data = response.json()
        if resp_data['status']:
            return JsonResponse({
                'access_code': resp_data['data']['access_code'],
                'reference': reference,
            })
        else:
            payment.status = 'failed'
            payment.save()
            return JsonResponse({'error': resp_data.get('message', 'Initialization failed')}, status=400)
    else:
        payment.status = 'failed'
        payment.save()
        return JsonResponse({'error': 'Gateway error'}, status=500)


@staff_member_required
def admin_manage_announcements(request):
    announcements = Announcement.objects.all().order_by('-created_at')
    return render(request, 'admin/announcements.html', {'announcements': announcements})

@staff_member_required
def admin_create_announcement(request):
    if request.method == 'POST':
        form = AnnouncementForm(request.POST)
        if form.is_valid():
            announcement = form.save(commit=False)
            announcement.created_by = request.user
            announcement.save()
            messages.success(request, f'Announcement "{announcement.title}" created.')
            return redirect('admin_manage_announcements')
    else:
        form = AnnouncementForm()
    return render(request, 'admin/create_announcement.html', {'form': form})

@staff_member_required
def admin_delete_announcement(request, announcement_id):
    announcement = get_object_or_404(Announcement, id=announcement_id)
    title = announcement.title
    announcement.delete()
    messages.success(request, f'Announcement "{title}" deleted.')
    return redirect('admin_manage_announcements')

@login_required
def get_announcements(request):
    announcements = Announcement.objects.filter(is_active=True).order_by('-created_at')[:20]
    data = []
    for ann in announcements:
        read = UserAnnouncementRead.objects.filter(user=request.user, announcement=ann).exists()
        data.append({
            'id': ann.id,
            'title': ann.title,
            'message': ann.message,
            'created_at': ann.created_at.strftime('%b %d, %Y %H:%M'),
            'read': read,
        })
    unread_count = sum(1 for item in data if not item['read'])
    return JsonResponse({'announcements': data, 'unread_count': unread_count})

@login_required
@require_POST
def mark_announcement_read(request, announcement_id):
    announcement = get_object_or_404(Announcement, id=announcement_id, is_active=True)
    UserAnnouncementRead.objects.get_or_create(user=request.user, announcement=announcement)
    return JsonResponse({'status': 'ok'})


# ── Staff ─────────────────────────────────────────────────────────────────────
@staff_or_admin_required
def staff_create_landlord(request):
    if request.method == 'POST':
        form = StaffLandlordCreationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = True
            user.save()
            UserProfile.objects.create(
                user=user,
                user_type='landlord',
                phone_number=form.cleaned_data.get('phone_number', ''),
                address=form.cleaned_data.get('address', ''),
                email_verified=False,
            )
            # Send verification email
            otp = OTP.create_otp(user)
            send_otp_email(user, otp.code)
            messages.success(request, f"Landlord account for {user.username} created. They must verify their email.")
            return redirect('staff_create_landlord')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = StaffLandlordCreationForm()

    return render(request, 'staff/create_landlord.html', {'form': form})


@staff_or_admin_required
def staff_register_property(request):
    if request.method == 'POST':
        form = StaffPropertyRegistrationForm(request.POST, request.FILES)
        if form.is_valid():
            prop = form.save()
            messages.success(request, f'Property "{prop.name}" registered for {prop.owner.username}.')
            return redirect('staff_register_property')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = StaffPropertyRegistrationForm()

    return render(request, 'staff/register_property.html', {'form': form})


class _InMemoryUploadCopy:
    """
    A minimal stand-in for Django's UploadedFile that owns its own bytes.

    request.FILES objects (and their underlying temp files) are only
    guaranteed to be valid for the lifetime of the request. Since the actual
    import now runs in a background thread that outlives the request/response
    cycle, we copy the upload into plain bytes up front and hand this wrapper
    to the background thread instead of the original file object.
    """

    def __init__(self, name, content_bytes):
        self.name = name
        self._buffer = io.BytesIO(content_bytes)

    def seek(self, pos):
        return self._buffer.seek(pos)

    def read(self, *args, **kwargs):
        return self._buffer.read(*args, **kwargs)


def _run_property_import_in_background(uploaded_file_copy, progress_key):
    """
    Runs the (potentially very slow, 100k+ row) import off the request
    thread. Progress and the final result are written to the cache so the
    browser can poll `staff_import_properties_progress` for status.

    This is a plain Python thread rather than a real task queue, which is a
    reasonable stopgap for a single-worker deployment but has real limits:
    if the gunicorn worker process is restarted/redeployed mid-import, the
    thread (and the import) dies with it. For very large recurring imports,
    a proper background worker (Celery/RQ + Redis) is the durable answer.
    """
    cache_key = f'property_import_progress:{progress_key}'

    def progress_callback(current, total, created_count, message):
        percent = int((current / total) * 100) if total else 0
        cache.set(cache_key, {
            'status': 'running',
            'message': message,
            'percent': percent,
            'created_count': created_count,
            'done': False,
            'error': '',
            'rows': [],
        }, timeout=3600)

    try:
        created_count, account_rows = import_properties_from_uploaded_file(
            uploaded_file_copy, progress_callback=progress_callback,
        )
        cache.set(cache_key, {
            'status': 'done',
            'message': 'Import complete.' if created_count else 'No valid property rows were found. Nothing was saved.',
            'percent': 100,
            'created_count': created_count,
            'done': True,
            'error': '',
            'rows': account_rows,
        }, timeout=3600)
    except Exception as exc:
        cache.set(cache_key, {
            'status': 'error',
            'message': 'Import failed.',
            'percent': 0,
            'created_count': 0,
            'done': True,
            'error': str(exc),
            'rows': [],
        }, timeout=3600)
    finally:
        # Each thread gets its own DB connection; close it explicitly so
        # long-running background threads don't leak idle connections
        # against the (remote, connection-limited) Neon database.
        from django.db import connections
        connections.close_all()


_PROGRESS_PAGE_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Importing properties…</title>
  <style>
    body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; max-width: 640px; margin: 60px auto; padding: 0 20px; color: #1a1a1a; }}
    .bar-track {{ background: #e5e7eb; border-radius: 8px; height: 20px; overflow: hidden; margin: 16px 0; }}
    .bar-fill {{ background: #16a34a; height: 100%; width: 0%; transition: width 0.4s ease; }}
    .status {{ color: #4b5563; }}
    .error {{ color: #b91c1c; font-weight: 600; }}
    .success {{ color: #15803d; font-weight: 600; }}
    a.button {{ display: inline-block; margin-top: 20px; padding: 10px 18px; background: #111827; color: #fff; text-decoration: none; border-radius: 6px; }}
  </style>
</head>
<body>
  <h2>Importing properties…</h2>
  <p class="status" id="status-message">Starting import…</p>
  <div class="bar-track"><div class="bar-fill" id="bar-fill"></div></div>
  <p id="percent-text">0%</p>
  <div id="result"></div>

  <script>
    const progressUrl = "{progress_url}";
    const doneUrl = "{done_url}";

    async function poll() {{
      try {{
        const res = await fetch(progressUrl, {{ cache: "no-store" }});
        const data = await res.json();

        document.getElementById("status-message").textContent = data.message || "Working…";
        document.getElementById("bar-fill").style.width = (data.percent || 0) + "%";
        document.getElementById("percent-text").textContent = (data.percent || 0) + "%";

        if (data.done) {{
          const resultEl = document.getElementById("result");
          if (data.status === "error") {{
            resultEl.innerHTML = '<p class="error">Import failed: ' + (data.error || "unknown error") + '</p>' +
              '<a class="button" href="' + doneUrl + '">Back to import page</a>';
          }} else {{
            resultEl.innerHTML = '<p class="success">' + data.created_count + ' property record(s) imported successfully.</p>' +
              '<a class="button" href="' + doneUrl + '">Back to import page</a>';
          }}
          return;
        }}
        setTimeout(poll, 1500);
      }} catch (e) {{
        document.getElementById("status-message").textContent = "Lost connection to progress updates — the import is still running in the background. Reloading…";
        setTimeout(() => window.location.reload(), 3000);
      }}
    }}
    poll();
  </script>
</body>
</html>
"""


@staff_or_admin_required
def staff_import_properties(request):
    profile = getattr(request.user, 'userprofile', None)
    if not profile or profile.user_type not in ['admin', 'staff']:
        messages.error(request, 'Bulk property imports are only available to staff and admin users.')
        return redirect('dashboard')

    form = PropertyBulkUploadForm()
    created_count = 0
    account_rows = []
    progress_key = request.GET.get('progress_key') or ''

    if request.method == 'POST':
        form = PropertyBulkUploadForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = request.FILES.get('file')
            if uploaded_file is None:
                messages.error(request, 'Please choose a file to upload.')
                return redirect('staff_import_properties')

            # Read the whole upload into memory now, while we still have the
            # real request-bound file object, so the background thread has
            # its own independent copy to work from.
            uploaded_file.seek(0)
            file_bytes = uploaded_file.read()
            file_copy = _InMemoryUploadCopy(uploaded_file.name, file_bytes)

            new_progress_key = uuid.uuid4().hex
            cache.set(f'property_import_progress:{new_progress_key}', {
                'status': 'running',
                'message': 'Starting import…',
                'percent': 0,
                'created_count': 0,
                'done': False,
                'error': '',
                'rows': [],
            }, timeout=3600)

            thread = threading.Thread(
                target=_run_property_import_in_background,
                args=(file_copy, new_progress_key),
                daemon=True,
            )
            thread.start()

            progress_url = reverse('staff_import_properties_progress', args=[new_progress_key])
            done_url = reverse('staff_import_properties')
            html = _PROGRESS_PAGE_TEMPLATE.format(progress_url=progress_url, done_url=done_url)
            return HttpResponse(html)
        else:
            messages.error(request, 'Please upload a valid CSV or Excel file.')

    return render(request, 'staff/import_properties.html', {
        'form': form,
        'created_count': created_count,
        'account_rows': account_rows,
        'progress_key': progress_key,
    })


@staff_or_admin_required
@require_GET
def staff_import_properties_progress(request, progress_key):
    progress_data = cache.get(f'property_import_progress:{progress_key}', {})
    payload = {
        'status': progress_data.get('status', 'idle'),
        'message': progress_data.get('message', 'Awaiting import...'),
        'percent': progress_data.get('percent', 0),
        'created_count': progress_data.get('created_count', 0),
        'done': progress_data.get('done', False),
        'error': progress_data.get('error', ''),
        'rows': progress_data.get('rows', []),
    }
    return JsonResponse(payload)


@staff_or_admin_required
def search_landlords(request):
    query = request.GET.get('q', '').strip()
    if len(query) < 2:
        return JsonResponse({'results': []})

    landlords = User.objects.filter(
        userprofile__user_type='landlord'
    ).filter(
        Q(username__icontains=query) |
        Q(email__icontains=query) |
        Q(first_name__icontains=query) |
        Q(last_name__icontains=query)
    ).select_related('userprofile')[:10]

    results = []
    for landlord in landlords:
        full_name = landlord.get_full_name() or landlord.username
        results.append({
            'id': landlord.id,
            'text': f"{full_name} ({landlord.email})",
            'username': landlord.username,
            'email': landlord.email,
        })
    return JsonResponse({'results': results})


# ── Admin: Create Staff/Admin User ────────────────────────────────────────────
@staff_member_required
def admin_create_user(request):
    profile = request.user.userprofile
    if profile.user_type != 'admin':
        messages.error(request, "Only admins can create user accounts.")
        return redirect('dashboard')

    if request.method == 'POST':
        form = StaffLandlordCreationForm(request.POST)
        user_type = request.POST.get('user_type', 'staff')
        if user_type not in ['landlord', 'staff', 'field_staff', 'admin']:
            user_type = 'staff'
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = True
            user.is_staff = user_type in ['staff', 'field_staff', 'admin']
            user.save()
            UserProfile.objects.create(
                user=user,
                user_type=user_type,
                phone_number=form.cleaned_data.get('phone_number', ''),
                address=form.cleaned_data.get('address', ''),
                email_verified=True,
            )
            messages.success(request, f'User "{user.username}" ({user_type}) was created and verified successfully.')
            return redirect('admin_manage_users')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = StaffLandlordCreationForm()

    return render(request, 'admin/create_user.html', {'form': form})


# ── Admin: Pay Bypass ─────────────────────────────────────────────────────────
@staff_member_required
def admin_pay_bypass(request):
    profile = request.user.userprofile
    if profile.user_type != 'admin':
        messages.error(request, "Only admins can use the pay bypass tool.")
        return redirect('dashboard')

    search_user = None
    user_payments = []        # property-based outstanding payments
    sanitation_payments = []  # sanitation (property=None) outstanding payments
    search_query = request.GET.get('q', '').strip()

    if search_query:
        try:
            search_user = User.objects.select_related('userprofile').get(
                Q(username__iexact=search_query) | Q(email__iexact=search_query)
            )
            now = timezone.now()

            # ── Property-based payments ──────────────────────────────────────
            for prop in Property.objects.filter(owner=search_user):
                for rate in PaymentRate.objects.filter(
                    property_type=prop.property_type, is_active=True, is_sanitation=False
                ):
                    payment = Payment.objects.filter(
                        landlord=search_user, property=prop, payment_rate=rate
                    ).filter(
                        django_models.Q(expires_at__isnull=True) | django_models.Q(expires_at__gt=now)
                    ).filter(status='success').first()
                    if not payment:
                        pending = Payment.objects.filter(
                            landlord=search_user, property=prop, payment_rate=rate, status='pending'
                        ).first()
                        user_payments.append({
                            'property': prop,
                            'rate': rate,
                            'payment': pending,
                        })

            # ── Sanitation payments (apply to landlords AND tenants) ─────────
            user_type = search_user.userprofile.user_type
            if user_type in ['landlord', 'tenant']:
                for rate in PaymentRate.objects.filter(is_sanitation=True, is_active=True):
                    payment = Payment.objects.filter(
                        landlord=search_user, property=None, payment_rate=rate, status='success',
                    ).filter(
                        django_models.Q(expires_at__isnull=True) | django_models.Q(expires_at__gt=now)
                    ).first()
                    if not payment:
                        pending = Payment.objects.filter(
                            landlord=search_user, property=None, payment_rate=rate, status='pending'
                        ).first()
                        sanitation_payments.append({
                            'rate': rate,
                            'payment': pending,
                        })

        except User.DoesNotExist:
            messages.error(request, f'No user found with username or email "{search_query}".')

    return render(request, 'admin/pay_bypass.html', {
        'search_query': search_query,
        'search_user': search_user,
        'user_payments': user_payments,
        'sanitation_payments': sanitation_payments,
    })


@staff_member_required
def admin_pay_bypass_update(request, property_id, rate_id):
    profile = request.user.userprofile
    if profile.user_type != 'admin':
        messages.error(request, "Only admins can use the pay bypass tool.")
        return redirect('dashboard')

    if request.method == 'POST':
        rate        = get_object_or_404(PaymentRate, id=rate_id)
        redirect_q  = request.POST.get('q', '')
        paid_at     = timezone.now()

        # property_id == 0 signals a sanitation payment (no property)
        if property_id == 0:
            landlord_id = request.POST.get('landlord_id')
            if not landlord_id:
                messages.error(request, "Landlord not identified for sanitation bypass.")
                return redirect(f'/management/pay-bypass/?q={redirect_q}')
            landlord = get_object_or_404(User, id=landlord_id)
            validity_days = 30
            existing = Payment.objects.filter(landlord=landlord, property=None, payment_rate=rate)
            if existing.exists():
                existing.update(
                    status='success',
                    paid_at=paid_at,
                    expires_at=paid_at + timezone.timedelta(days=validity_days),
                )
            else:
                Payment.objects.create(
                    landlord=landlord,
                    property=None,
                    payment_rate=rate,
                    amount=rate.amount,
                    reference=f'BYPASS-SAN-{timezone.now().strftime("%Y%m%d%H%M%S")}-{landlord.id}-{rate.id}',
                    status='success',
                    paid_at=paid_at,
                    expires_at=paid_at + timezone.timedelta(days=validity_days),
                )
            messages.success(request, f'Sanitation payment "{rate.name}" for {landlord.username} marked as paid.')
        else:
            prop     = get_object_or_404(Property, id=property_id)
            landlord = prop.owner
            validity_days = 30 if rate.is_sanitation else 365
            existing = Payment.objects.filter(landlord=landlord, property=prop, payment_rate=rate)
            if existing.exists():
                existing.update(
                    status='success',
                    paid_at=paid_at,
                    expires_at=paid_at + timezone.timedelta(days=validity_days),
                )
            else:
                Payment.objects.create(
                    landlord=landlord,
                    property=prop,
                    payment_rate=rate,
                    amount=rate.amount,
                    reference=f'BYPASS-{timezone.now().strftime("%Y%m%d%H%M%S")}-{prop.id}-{rate.id}',
                    status='success',
                    paid_at=paid_at,
                    expires_at=paid_at + timezone.timedelta(days=validity_days),
                )
            messages.success(request, f'Payment for "{prop.name}" / "{rate.name}" marked as paid.')

        return redirect(f'/management/pay-bypass/?q={redirect_q}')

    return redirect('admin_pay_bypass')


# ── Admin: Defaulters ───────────────────────────────────────────────────────
@staff_member_required
def admin_defaulters_list(request):
    profile = request.user.userprofile
    if profile.user_type not in ['admin', 'staff', 'field_staff']:
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    defaulters = []
    landlords = User.objects.filter(userprofile__user_type='landlord').select_related('userprofile')
    now = timezone.now()

    for landlord in landlords:
        for prop in Property.objects.filter(owner=landlord):
            for rate in PaymentRate.objects.filter(property_type=prop.property_type, is_active=True):
                valid = Payment.objects.filter(
                    landlord=landlord, property=prop, payment_rate=rate, status='success',
                ).filter(
                    django_models.Q(expires_at__isnull=True) | django_models.Q(expires_at__gt=now)
                ).exists()
                if not valid:
                    defaulters.append({
                        'landlord': landlord,
                        'property': prop,
                        'rate': rate,
                    })

    return render(request, 'admin/defaulters_list.html', {'defaulters': defaulters})


@staff_member_required
def admin_export_defaulters(request):
    profile = request.user.userprofile
    if profile.user_type not in ['admin', 'staff', 'field_staff']:
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Defaulters"

    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill("solid", fgColor="1E3A5F")
    header_align = Alignment(horizontal="center", vertical="center")
    thin = Side(border_style="thin", color="D1D5DB")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    headers = [
        "Landlord Username", "Full Name", "Email", "Phone",
        "Property Name", "Address", "District", "Property Type",
        "No. of Units", "Rate Name", "Amount Due (₦)", "Property Registered"
    ]
    col_widths = [20, 22, 28, 16, 25, 32, 14, 16, 12, 28, 18, 22]

    for i, (h, w) in enumerate(zip(headers, col_widths), 1):
        cell = ws.cell(row=1, column=i, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = border
        ws.column_dimensions[get_column_letter(i)].width = w

    ws.row_dimensions[1].height = 22

    landlords = User.objects.filter(userprofile__user_type='landlord').select_related('userprofile')
    row_num = 2
    alt_fill = PatternFill("solid", fgColor="F7F8FA")
    now = timezone.now()

    for landlord in landlords:
        for prop in Property.objects.filter(owner=landlord):
            for rate in PaymentRate.objects.filter(property_type=prop.property_type, is_active=True):
                valid = Payment.objects.filter(
                    landlord=landlord, property=prop, payment_rate=rate, status='success',
                ).filter(
                    django_models.Q(expires_at__isnull=True) | django_models.Q(expires_at__gt=now)
                ).exists()
                if not valid:
                    row_fill = alt_fill if row_num % 2 == 0 else PatternFill("solid", fgColor="FFFFFF")
                    row_data = [
                        landlord.username,
                        landlord.get_full_name() or '—',
                        landlord.email,
                        getattr(landlord.userprofile, 'phone_number', '') or '—',
                        prop.name,
                        prop.address,
                        prop.district.title(),
                        prop.get_property_type_display(),
                        prop.num_units,
                        rate.name,
                        float(rate.amount),
                        prop.created_at.strftime("%Y-%m-%d") if prop.created_at else '—',
                    ]
                    for col, value in enumerate(row_data, 1):
                        cell = ws.cell(row=row_num, column=col, value=value)
                        cell.border = border
                        cell.fill = row_fill
                        cell.alignment = Alignment(vertical="center")
                        if col == 11:
                            cell.number_format = '#,##0.00'
                    row_num += 1

    if row_num == 2:
        ws.cell(row=2, column=1, value="No defaulters found.")

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    response = HttpResponse(
        output.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="defaulters_enforcement_{timezone.now().strftime("%Y%m%d")}.xlsx"'
    return response


# ── Forgot Password views ────────────────────────────────────────────────────
def forgot_password(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    ip = _get_client_ip(request)

    if request.method == 'POST':
        # Max 5 password-reset requests per IP per hour
        rl_key = f'forgot_password:{ip}'
        if _is_rate_limited(rl_key, limit=5, window_seconds=3600):
            messages.error(
                request,
                'Too many password reset attempts. Please try again in an hour.'
            )
            return render(request, 'auth/forgot_password.html', {'form': ForgotPasswordForm()})

        form = ForgotPasswordForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            user = User.objects.filter(email=email).first()

            if user is not None:
                otp = OTP.create_otp(user)
                if send_forgot_password_email(user, otp.code):
                    request.session['password_reset_user_id'] = user.id
                    messages.success(request, f'An OTP has been sent to {email}. Please check your email.')
                    return redirect('verify_forgot_password_otp')
                else:
                    messages.error(request, 'Failed to send email. Please try again.')
                    otp.delete()
            else:
                # Don't reveal that email doesn't exist
                messages.info(request, 'If that email is registered, an OTP has been sent.')
                return redirect('login')
    else:
        form = ForgotPasswordForm()

    return render(request, 'auth/forgot_password.html', {'form': form})

def verify_forgot_password_otp(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    user_id = request.session.get('password_reset_user_id')
    if not user_id:
        messages.error(request, 'Password reset session expired. Please try again.')
        return redirect('forgot_password')

    user = get_object_or_404(User, id=user_id)

    try:
        user_otp = OTP.objects.get(user=user)
    except OTP.DoesNotExist:
        messages.error(request, 'OTP not found. Please request a new one.')
        return redirect('forgot_password')

    if request.method == 'POST':
        form = ForgotPasswordOTPForm(request.POST)
        if form.is_valid():
            code = form.cleaned_data['otp_code']
            if not user_otp.is_valid():
                messages.error(request, 'OTP expired. A new one has been sent.')
                OTP.create_otp(user)
                send_forgot_password_email(user, OTP.objects.get(user=user).code)
                return redirect('verify_forgot_password_otp')

            if user_otp.verify(code):
                request.session['password_reset_verified'] = True
                messages.success(request, 'OTP verified. Please set your new password.')
                return redirect('reset_password')
            else:
                messages.error(request, 'Invalid OTP code. Please try again.')
    else:
        form = ForgotPasswordOTPForm()

    return render(request, 'auth/verify_forgot_password_otp.html', {
        'form': form,
        'user_email': user.email,
    })


def reset_password(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if not request.session.get('password_reset_verified'):
        messages.error(request, 'Please verify your OTP first.')
        return redirect('forgot_password')

    user_id = request.session.get('password_reset_user_id')
    if not user_id:
        messages.error(request, 'Password reset session expired. Please try again.')
        return redirect('login')

    user = get_object_or_404(User, id=user_id)

    if request.method == 'POST':
        form = ResetPasswordForm(request.POST)
        if form.is_valid():
            new_password = form.cleaned_data['password']
            user.set_password(new_password)
            user.save()

            # Clear session
            request.session.pop('password_reset_user_id', None)
            request.session.pop('password_reset_verified', None)

            messages.success(request, 'Password reset successfully! You can now login with your new password.')
            return redirect('login')
    else:
        form = ResetPasswordForm()

    return render(request, 'auth/reset_password.html', {
        'form': form,
        'user_email': user.email,
    })


def resend_forgot_password_otp(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    ip = _get_client_ip(request)

    user_id = request.session.get('password_reset_user_id')
    if not user_id:
        messages.error(request, 'Session expired. Please start over.')
        return redirect('forgot_password')

    # Max 3 resends per session IP per 10 minutes
    rl_key = f'resend_fp_otp:{user_id}:{ip}'
    if _is_rate_limited(rl_key, limit=3, window_seconds=600):
        messages.error(request, 'Too many resend requests. Please wait a few minutes.')
        return redirect('verify_forgot_password_otp')

    user = get_object_or_404(User, id=user_id)
    otp = OTP.create_otp(user)
    if send_forgot_password_email(user, otp.code):
        messages.success(request, f'A new code has been sent to {user.email}.')
    else:
        messages.error(request, 'Failed to send email. Please try again.')
    return redirect('verify_forgot_password_otp')


# ── ADD THIS TO views.py ──────────────────────────────────────────────────────
# Place this function anywhere after the existing staff_register_property view.
# It requires no new imports beyond what views.py already has.
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def staff_verify_payment(request):
    """
    Staff / Admin tool: look up a payment by its reference number and display
    full verification details — landlord, property, amount, validity, and
    whether every active rate for that property is currently paid.
    """
    profile = request.user.userprofile
    if profile.user_type not in ['admin', 'staff', 'field_staff']:
        messages.error(request, 'Access denied.')
        return redirect('dashboard')

    result   = None   # Payment object if found
    error    = None   # Human-readable error string
    ref      = ''     # The submitted reference value

    if request.method == 'POST':
        ref = request.POST.get('reference', '').strip()

        if not ref:
            error = 'Please enter a receipt / reference number.'
        else:
            try:
                payment = (
                    Payment.objects
                    .select_related('landlord', 'landlord__userprofile', 'property', 'payment_rate')
                    .get(reference=ref)
                )

                # Build a full picture of this property's payment status
                prop        = payment.property
                active_rates = PaymentRate.objects.filter(
                    property_type=prop.property_type, is_active=True
                )

                coverage = []
                all_paid = True
                for rate in active_rates:
                    vp = get_latest_valid_payment(prop, rate)
                    covered = vp is not None
                    if not covered:
                        all_paid = False
                    coverage.append({
                        'rate':    rate,
                        'payment': vp,
                        'covered': covered,
                    })

                result = {
                    'payment':       payment,
                    'property':      prop,
                    'landlord':      payment.landlord,
                    'coverage':      coverage,
                    'all_paid':      all_paid,
                    'is_this_valid': payment.status == 'success' and not payment.is_expired,
                }

            except Payment.DoesNotExist:
                error = f'No payment record found for reference "{ref}". Please check and try again.'

    return render(request, 'staff/verify_payment.html', {
        'result': result,
        'error':  error,
        'ref':    ref,
    })

# ── Public Receipt Lookup (no login required) ─────────────────────────────────
@require_GET
def public_lookup_receipt(request):
    """
    AJAX endpoint — publicly accessible, no login required.
    Accepts ?ref=<receipt_reference> and returns JSON with payment details.
    Only surfaces successfully paid, non-expired receipts.
    """
    ref = request.GET.get('ref', '').strip()
    if not ref:
        return JsonResponse({'found': False, 'error': 'Please enter a receipt / reference number.'})

    try:
        payment = Payment.objects.select_related(
            'landlord', 'property', 'payment_rate'
        ).get(reference=ref, status='success')

        expired = payment.is_expired
        days_remaining = payment.days_remaining

        data = {
            'found':          True,
            'valid':          not expired,
            'reference':      payment.reference,
            'amount':         str(payment.amount),
            'property_name':  payment.property.name if payment.property else 'Environmental Sanitation Levy',
            'property_type':  payment.property.get_property_type_display() if payment.property else 'Sanitation',
            'property_address': payment.property.address if payment.property else 'N/A',
            'district':       payment.property.get_district_display() if payment.property and hasattr(payment.property, 'get_district_display') else (payment.property.district if payment.property else 'N/A'),
            'landlord_name':  payment.landlord.get_full_name() or payment.landlord.username,
            'rate_name':      payment.payment_rate.name if payment.payment_rate else '—',
            'paid_at':        payment.paid_at.strftime('%d %B %Y, %I:%M %p') if payment.paid_at else '—',
            'expires_at':     payment.expires_at.strftime('%d %B %Y') if payment.expires_at else '—',
            'days_remaining': days_remaining,
            'expired':        expired,
        }
    except Payment.DoesNotExist:
        data = {'found': False, 'error': f'No successful payment found for reference "{ref}". Please check and try again.'}

    return JsonResponse(data)

@login_required
@verified_email_required
def tenant_payments(request):
    profile = request.user.userprofile
    if profile.user_type != 'tenant':
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    # Only sanitation rates
    sanitation_rates = PaymentRate.objects.filter(is_sanitation=True, is_active=True)
    now = timezone.now()

    obligations = []
    paid_items = []
    for rate in sanitation_rates:
        # Check for a valid (non-expired) successful payment by this tenant for that rate
        valid_payment = Payment.objects.filter(
            landlord=request.user,
            payment_rate=rate,
            status='success',
            property=None,          # sanitation payments have no property
        ).filter(
            django_models.Q(expires_at__isnull=True) | django_models.Q(expires_at__gt=now)
        ).first()

        if valid_payment:
            paid_items.append({'rate': rate, 'payment': valid_payment})
        else:
            obligations.append({'rate': rate, 'amount': rate.amount})

    # Full payment history for tenant
    payments = Payment.objects.filter(
        landlord=request.user, property=None
    ).select_related('payment_rate').order_by('-created_at')

    context = {
        'obligations': obligations,
        'paid_coverage': paid_items,
        'payments': payments,
        'successful_payments_count': payments.filter(status='success').count(),
    }
    return render(request, 'tenant/payments.html', context)


# ── Bye-Law Pages ─────────────────────────────────────────────────────────────

def bylaw_preliminary(request):
    return render(request, 'by_laws/prelimenary.html')

def bylaw_enabling_law(request):
    return render(request, 'by_laws/enabling_law.html')

def bylaw_marriages(request):
    return render(request, 'by_laws/Registrition_of_marriages.html')

def bylaw_motor_parks(request):
    return render(request, 'by_laws/motor_parks.html')

def bylaw_environmental_sanitation(request):
    return render(request, 'by_laws/environmental_sanitation.html')

def bylaw_allied_matters(request):
    return render(request, 'by_laws/allied_matters.html')

def bylaw_borehole_drilling(request):
    return render(request, 'by_laws/borehole_drilling.html')

def bylaw_commercial_pos_operators(request):
    return render(request, 'by_laws/commercial_pos_operators.html')

def bylaw_community_tax(request):
    return render(request, 'by_laws/community_tax.html')

def bylaw_construction_permits(request):
    return render(request, 'by_laws/construction_permits.html')

def bylaw_contractors(request):
    return render(request, 'by_laws/contractors.html')

def bylaw_control_of_advertisement(request):
    return render(request, 'by_laws/control_of_advertisement.html')



def bylaw_cutting_road_tar(request):
    return render(request, 'by_laws/cutting_of_road_tar.html')

def bylaw_foodstuff_regulation(request):
    return render(request, 'by_laws/foodstuff_regulation.html')

def bylaw_house_numbering(request):
    return render(request, 'by_laws/house_numbering.html')

def bylaw_liquor_licensing(request):
    return render(request, 'by_laws/liquor_licensing.html')

def bylaw_market_regulation(request):
    return render(request, 'by_laws/market_regulation.html')

def bylaw_mobile_advertisement(request):
    return render(request, 'by_laws/mobile_advertisement.html')

def bylaw_motorcycle_uses(request):
    return render(request, 'by_laws/motorcycle_uses.html')

def bylaw_movement_keeping_dogs(request):
    return render(request, 'by_laws/movement_and_keeping_of_dogs.html')

def bylaw_parking_traffic_control(request):
    return render(request, 'by_laws/parking_and_traffic_control.html')

def bylaw_pest_control(request):
    return render(request, 'by_laws/pest_control.html')

def bylaw_public_toilet(request):
    return render(request, 'by_laws/public_toilet.html')

def bylaw_refuse_operation(request):
    return render(request, 'by_laws/refuse_operation.html')

def bylaw_laundry_registration(request):
    return render(request, 'by_laws/registration_of_laundry_houses.html')

def bylaw_regulated_premises(request):
    return render(request, 'by_laws/regulated_premises.html')

def bylaw_tenement_rate(request):
    return render(request, 'by_laws/tenement_rate.html')

def bylaw_tv_license(request):
    return render(request, 'by_laws/tv_license.html')

def bylaw_wrong_parking(request):
    return render(request, 'by_laws/wrong_parking.html')