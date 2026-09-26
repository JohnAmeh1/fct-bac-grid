from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import UserProfile, Property, Complaint, SiteConfiguration, PaymentRate, Payment, Announcement
import re

# ---------------------------------------------------------------------------
# Disposable / throwaway email domains that bots commonly use.
# Add more as you spot them in the Django admin.
# ---------------------------------------------------------------------------
DISPOSABLE_EMAIL_DOMAINS = {
    'mailinator.com', 'guerrillamail.com', 'guerrillamail.net',
    'guerrillamail.org', 'guerrillamail.biz', 'guerrillamail.de',
    'guerrillamailblock.com', 'sharklasers.com', 'spam4.me',
    'trashmail.com', 'trashmail.me', 'trashmail.net', 'trashmail.at',
    'trashmail.io', 'trashmail.org', 'dispostable.com', 'yopmail.com',
    'yopmail.fr', 'cool.fr.nf', 'jetable.fr.nf', 'nospam.ze.tc',
    'nomail.xl.cx', 'mega.zik.dj', 'speed.1s.fr', 'courriel.fr.nf',
    'moncourrier.fr.nf', 'monemail.fr.nf', 'monmail.fr.nf',
    'tempmail.com', 'temp-mail.org', 'fakeinbox.com', 'mailnull.com',
    'maildrop.cc', 'throwam.com', 'throwaway.email',
    'spamgourmet.com', 'spamgourmet.net', 'spamgourmet.org',
    'getairmail.com', 'filzmail.com', 'discard.email', 'spamthisplease.com',
    'binkmail.com', 'bobmail.info', 'chammy.info', 'devnullmail.com',
    'evilhed.com', 'spamhole.com', 'spamoff.de', 'smellfear.com',
    'thisisnotmyrealemail.com', 'turboemail.org', 'wegwerfmail.de',
    'wegwerfmail.net', 'wegwerfmail.org', 'rmqkr.net', 'hatespam.org',
    'spamgob.com', 'supergreatmail.com', 'kurzepost.de', 'objectmail.com',
    'spamkon.de', 'proxymail.eu', 'rcpt.at', 'spam.la', 'antispam.de',
    'spamfree24.org', 'spamfree24.de', 'spamfree24.eu', 'spamfree24.net',
    'nwldx.com', 'spamstack.net', 'fakedemail.com', 'mailnew.com',
}


USER_TYPE_CHOICES = (
    ('landlord', 'Landlord / Property Owner'),
)

class SignupForm(UserCreationForm):
    email        = forms.EmailField(required=True)
    phone_number = forms.CharField(max_length=15, required=False)
    address      = forms.CharField(max_length=255, required=False)
    user_type    = forms.ChoiceField(choices=USER_TYPE_CHOICES, required=True)

    # ── Honeypot: bots fill every field; real users leave this blank ──────────
    # Rendered as display:none in the template so humans never see it.
    website = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'tabindex': '-1', 'autocomplete': 'off'}),
        label='',
    )

    class Meta:
        model  = User
        fields = ('username', 'email', 'first_name', 'last_name', 'password1', 'password2')

    # ── Username: letters, digits, underscores, hyphens only ─────────────────
    def clean_username(self):
        username = self.cleaned_data.get('username', '')
        if not re.match(r'^[a-zA-Z0-9_\-]+$', username):
            raise forms.ValidationError(
                'Username may only contain letters, numbers, underscores, and hyphens.'
            )
        # Reject purely random-looking strings (10+ consecutive lowercase letters)
        if re.match(r'^[a-z]{10,}$', username):
            raise forms.ValidationError(
                'Please choose a more descriptive username.'
            )
        return username

    # ── Email: no disposable domains; no duplicate accounts ──────────────────
    def clean_email(self):
        email = self.cleaned_data.get('email', '').lower().strip()
        domain = email.split('@')[-1] if '@' in email else ''
        if domain in DISPOSABLE_EMAIL_DOMAINS:
            raise forms.ValidationError(
                'Please use a real email address. Disposable / temporary email '
                'addresses are not accepted.'
            )
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                'An account with this email address already exists.'
            )
        return email

    # ── Honeypot check ────────────────────────────────────────────────────────
    def clean_website(self):
        value = self.cleaned_data.get('website', '')
        if value:
            # Bot filled the hidden field — silently reject
            raise forms.ValidationError('Invalid submission.')
        return value

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email      = self.cleaned_data['email']
        user.first_name = self.cleaned_data.get('first_name', '')
        user.last_name  = self.cleaned_data.get('last_name', '')
        if commit:
            user.save()
            UserProfile.objects.create(
                user=user,
                user_type=self.cleaned_data['user_type'],
                phone_number=self.cleaned_data.get('phone_number', ''),
                address=self.cleaned_data.get('address', ''),
                email_verified=False,
            )
        return user


class LoginForm(forms.Form):
    username = forms.CharField()
    password = forms.CharField(widget=forms.PasswordInput)
    remember_me = forms.BooleanField(required=False)


class ProfileUpdateForm(forms.ModelForm):
    first_name = forms.CharField(max_length=30, required=True)
    last_name = forms.CharField(max_length=30, required=True)
    email = forms.EmailField(required=True)

    class Meta:
        model = UserProfile
        fields = ['phone_number', 'address', 'bio']

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if self.user:
            self.fields['first_name'].initial = self.user.first_name
            self.fields['last_name'].initial = self.user.last_name
            self.fields['email'].initial = self.user.email

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip()
        qs = User.objects.filter(email__iexact=email)
        if self.user:
            qs = qs.exclude(pk=self.user.pk)
        if qs.exists():
            raise forms.ValidationError('An account with this email address already exists.')
        return email

    def email_changed(self):
        """True if the submitted email differs from the user's current email."""
        if not self.user:
            return False
        return self.cleaned_data.get('email', '').lower() != (self.user.email or '').lower()

    def save(self, commit=True, commit_email=True):
        """
        commit_email=False lets the caller apply the email separately
        (used for the OTP-gated email-change flow) instead of writing it
        straight to the User record.
        """
        profile = super().save(commit=False)
        if self.user:
            self.user.first_name = self.cleaned_data['first_name']
            self.user.last_name = self.cleaned_data['last_name']
            if commit_email:
                self.user.email = self.cleaned_data['email']
            self.user.save()
        if commit:
            profile.save()
        return profile


PROPERTY_TYPE_CHOICES = (
    ('residential', 'Residential'),
    ('commercial',  'Commercial'),
)

DISTRICT_CHOICES = (
    ('bwari',   'Bwari'),
    ('dutse',   'Dutse'),
    ('kawu',    'Kawu'),
    ('rubochi', 'Rubochi'),
    ('shere',   'Shere'),
    ('other',   'Other'),
)


class PropertyRegistrationForm(forms.Form):
    name          = forms.CharField(max_length=255, label='Property Name')
    address       = forms.CharField(max_length=500, label='Address')
    district      = forms.ChoiceField(choices=DISTRICT_CHOICES, label='District / Area')
    property_type = forms.ChoiceField(choices=PROPERTY_TYPE_CHOICES, label='Property Type')
    num_units     = forms.IntegerField(
        min_value=1, required=False, label='Number of Units',
        widget=forms.NumberInput(attrs={'placeholder': 'e.g. 4'})
    )
    latitude  = forms.DecimalField(max_digits=9, decimal_places=6, required=False, widget=forms.HiddenInput())
    longitude = forms.DecimalField(max_digits=9, decimal_places=6, required=False, widget=forms.HiddenInput())
    main_image = forms.ImageField(required=True, label='Main Property Image')
    image_1    = forms.ImageField(required=True, label='Additional Image 1')
    image_2    = forms.ImageField(required=True, label='Additional Image 2')
    image_3    = forms.ImageField(required=True, label='Additional Image 3')
    image_4    = forms.ImageField(required=False, label='Additional Image 4 (Optional)')
    image_5    = forms.ImageField(required=False, label='Additional Image 5 (Optional)')
    image_6    = forms.ImageField(required=False, label='Additional Image 6 (Optional)')
    num_flats = forms.IntegerField(
        min_value=0, required=False, label='Number of Flats',
        widget=forms.NumberInput(attrs={'placeholder': 'e.g. 4'}),
        help_text='For residential properties only. Used to calculate fixed per-unit rates.'
    )
    notes     = forms.CharField(
        required=False, label='Notes',
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Any additional details…'})
    )
    # Landlord account this property is registered under. Only required
    # (and only shown) when a staff / field_staff member fills the form on
    # a landlord's behalf — see `require_owner` below. For a landlord
    # filling out their own registration, this stays empty and the view
    # falls back to the logged-in user as owner.
    owner = forms.ModelChoiceField(
        queryset=User.objects.filter(userprofile__user_type='landlord'),
        required=False,
        widget=forms.HiddenInput()
    )
    landlord_search = forms.CharField(
        label='Landlord Account',
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'Search by landlord name, username, or email...',
            'autocomplete': 'off',
            'class': 'landlord-search-input'
        }),
    )

    def __init__(self, *args, require_owner=False, **kwargs):
        self.require_owner = require_owner
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        if self.require_owner and not cleaned_data.get('owner'):
            self.add_error('owner', 'Please search for and select the landlord this property belongs to.')
        prop_type = cleaned_data.get('property_type')
        num_flats = cleaned_data.get('num_flats')
        if prop_type == 'residential' and not num_flats:
            self.add_error('num_flats', 'Number of flats is required for residential properties.')
        return cleaned_data

    def save(self, owner):
        # When a landlord was explicitly selected (staff/field_staff flow),
        # that always takes precedence over whichever user is logged in.
        selected_owner = self.cleaned_data.get('owner')
        return Property.objects.create(
            owner=selected_owner or owner,
            name=self.cleaned_data['name'],
            address=self.cleaned_data['address'],
            district=self.cleaned_data['district'],
            property_type=self.cleaned_data['property_type'],
            num_units=self.cleaned_data.get('num_units') or 1,
            num_flats=self.cleaned_data.get('num_flats') or 0,
            latitude=self.cleaned_data.get('latitude') or None,
            longitude=self.cleaned_data.get('longitude') or None,
            main_image=self.cleaned_data['main_image'],
            image_1=self.cleaned_data['image_1'],
            image_2=self.cleaned_data['image_2'],
            image_3=self.cleaned_data['image_3'],
            image_4=self.cleaned_data['image_4'],
            image_5=self.cleaned_data['image_5'],
            image_6=self.cleaned_data['image_6'],
            notes=self.cleaned_data.get('notes', ''),
        )


class PropertyEditForm(forms.Form):
    name          = forms.CharField(max_length=255, label='Property Name')
    address       = forms.CharField(max_length=500, label='Address')
    district      = forms.ChoiceField(choices=DISTRICT_CHOICES, label='District / Area')
    property_type = forms.ChoiceField(choices=PROPERTY_TYPE_CHOICES, label='Property Type')
    num_units     = forms.IntegerField(min_value=1, required=False, label='Number of Units')
    latitude      = forms.DecimalField(max_digits=9, decimal_places=6, required=False, widget=forms.HiddenInput())
    longitude     = forms.DecimalField(max_digits=9, decimal_places=6, required=False, widget=forms.HiddenInput())
    main_image    = forms.ImageField(required=False, label='Main Property Image')
    image_1       = forms.ImageField(required=False, label='Additional Image 1')
    image_2       = forms.ImageField(required=False, label='Additional Image 2')
    image_3       = forms.ImageField(required=False, label='Additional Image 3')
    image_4       = forms.ImageField(required=False, label='Additional Image 4 (Optional)')
    image_5       = forms.ImageField(required=False, label='Additional Image 5 (Optional)')
    image_6       = forms.ImageField(required=False, label='Additional Image 6 (Optional)')
    num_flats     = forms.IntegerField(min_value=0, required=False, label='Number of Flats')
    notes         = forms.CharField(required=False, label='Notes', widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, property_obj=None, **kwargs):
        self.property_obj = property_obj
        super().__init__(*args, **kwargs)
        if property_obj is not None:
            self.fields['name'].initial = property_obj.name
            self.fields['address'].initial = property_obj.address
            self.fields['district'].initial = property_obj.district
            self.fields['property_type'].initial = property_obj.property_type
            self.fields['num_units'].initial = property_obj.num_units
            self.fields['num_flats'].initial = property_obj.num_flats
            self.fields['latitude'].initial = property_obj.latitude
            self.fields['longitude'].initial = property_obj.longitude
            self.fields['notes'].initial = property_obj.notes

    def clean(self):
        cleaned_data = super().clean()
        prop_type = cleaned_data.get('property_type')
        num_flats = cleaned_data.get('num_flats')
        if prop_type == 'residential' and not num_flats:
            self.add_error('num_flats', 'Number of flats is required for residential properties.')
        return cleaned_data

    def save(self, property_obj):
        property_obj.name = self.cleaned_data['name']
        property_obj.address = self.cleaned_data['address']
        property_obj.district = self.cleaned_data['district']
        property_obj.property_type = self.cleaned_data['property_type']
        property_obj.num_units = self.cleaned_data.get('num_units') or 1
        property_obj.num_flats = self.cleaned_data.get('num_flats') or 0
        property_obj.latitude = self.cleaned_data.get('latitude') or None
        property_obj.longitude = self.cleaned_data.get('longitude') or None
        property_obj.notes = self.cleaned_data.get('notes', '')

        for field_name in ['main_image', 'image_1', 'image_2', 'image_3', 'image_4', 'image_5', 'image_6']:
            uploaded_file = self.cleaned_data.get(field_name)
            if uploaded_file:
                setattr(property_obj, field_name, uploaded_file)

        property_obj.save()
        return property_obj


class PropertyBulkUploadForm(forms.Form):
    file = forms.FileField(
        label='CSV or Excel file',
        help_text='Upload the current property spreadsheet using the Bulk Property ID column to create imported property accounts.',
        widget=forms.ClearableFileInput(attrs={'accept': '.csv,.xlsx,.xls'})
    )


COMPLAINT_CATEGORY_CHOICES = (
    ('billing',   'Billing Issue'),
    ('property',  'Property Issue'),
    ('technical', 'Technical Problem'),
    ('general',   'General Enquiry'),
    ('other',     'Other'),
)


class ComplaintForm(forms.ModelForm):
    class Meta:
        model = Complaint
        fields = ['category', 'subject', 'description']
        widgets = {
            'description': forms.Textarea(attrs={
                'rows': 5,
                'placeholder': 'Please describe your complaint or enquiry in as much detail as possible…'
            }),
        }
        labels = {
            'category':    'Category',
            'subject':     'Subject',
            'description': 'Description',
        }


class AdminComplaintUpdateForm(forms.ModelForm):
    """Admin-only form to update complaint status and add notes."""
    class Meta:
        model = Complaint
        fields = ['status', 'admin_notes']
        widgets = {
            'admin_notes': forms.Textarea(attrs={
                'rows': 4,
                'placeholder': 'Add internal notes about this complaint (only visible to admins)…'
            }),
        }


class SiteConfigurationForm(forms.ModelForm):
    class Meta:
        model = SiteConfiguration
        fields = [
            'site_name',
            'site_tagline',
            'welcome_message',
            'contact_email',
            'contact_phone',
            'contact_address',
            'assessment_year',
            'assessment_deadline',
            'allow_registration',
            'maintenance_mode',
            'enable_email_notifications',
            'max_properties_per_landlord',
            'default_pagination_size',
            'system_email',
        ]
        widgets = {
            'contact_address': forms.Textarea(attrs={'rows': 2}),
            'welcome_message': forms.Textarea(attrs={'rows': 3}),
            'assessment_deadline': forms.DateInput(attrs={'type': 'date'}),
        }
        help_texts = {
            'assessment_year':             'Shown site‑wide (homepage notices, registration, dashboard) as the currently open assessment year.',
            'assessment_deadline':         'Late-payment surcharge notices use this date. Leave blank to hide the deadline notice.',
            'allow_registration':          'When unchecked, the signup page will be disabled.',
            'maintenance_mode':            'When checked, a maintenance banner is shown site‑wide.',
            'max_properties_per_landlord': 'Set to 0 for no limit.',
            'default_pagination_size':     'Default number of items per page across the system.',
        }


class BulkPropertyTypeChangeForm(forms.Form):
    source_property_type = forms.ChoiceField(
        choices=PROPERTY_TYPE_CHOICES,
        label='Change properties currently marked as',
    )
    target_property_type = forms.ChoiceField(
        choices=PROPERTY_TYPE_CHOICES,
        label='To property type',
    )
    confirm_change = forms.BooleanField(
        required=True,
        label='I understand this changes every matching property record.',
    )

    def clean(self):
        cleaned_data = super().clean()
        if (
            cleaned_data.get('source_property_type')
            and cleaned_data.get('source_property_type') == cleaned_data.get('target_property_type')
        ):
            self.add_error('target_property_type', 'Choose a different target property type.')
        return cleaned_data


class PaymentRateForm(forms.ModelForm):
    property_type = forms.ChoiceField(
        choices=PaymentRate._meta.get_field('property_type').choices,
        required=False,
        label='Property Type',
        help_text='Required for property-specific rates. Leave blank for sanitation rates.'
    )

    class Meta:
        model = PaymentRate
        fields = ['property_type', 'name', 'description', 'amount', 'is_active', 'is_per_unit', 'is_sanitation']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def clean(self):
        cleaned_data = super().clean()
        is_sanitation = cleaned_data.get('is_sanitation')
        property_type = cleaned_data.get('property_type')

        if is_sanitation:
            cleaned_data['property_type'] = None
        elif not property_type:
            raise forms.ValidationError('Please select a property type unless this is a sanitation rate.')

        return cleaned_data

class FixedResidentialRateForm(forms.ModelForm):
    """Form specifically for creating per-flat residential rates."""
    class Meta:
        model = PaymentRate
        fields = ['name', 'description', 'amount', 'is_active']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
        }
        labels = {
            'amount': 'Amount per Flat (₦)',
        }
        help_texts = {
            'amount': 'This amount will be multiplied by the number of flats in each residential property.',
        }

class AnnouncementForm(forms.ModelForm):
    class Meta:
        model = Announcement
        fields = ['title', 'message', 'is_active']
        widgets = {
            'message': forms.Textarea(attrs={'rows': 4}),
        }

class StaffLandlordCreationForm(forms.ModelForm):
    password1 = forms.CharField(label='Password', widget=forms.PasswordInput(attrs={'placeholder': 'Enter password'}))
    password2 = forms.CharField(label='Confirm Password', widget=forms.PasswordInput(attrs={'placeholder': 'Confirm password'}))
    phone_number = forms.CharField(max_length=15, required=False)
    address = forms.CharField(max_length=255, required=False)

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name']

    def clean_password2(self):
        p1 = self.cleaned_data.get('password1')
        p2 = self.cleaned_data.get('password2')
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("Passwords do not match.")
        return p2

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password1'])
        if commit:
            user.save()
        return user


class StaffPropertyRegistrationForm(forms.ModelForm):
    owner = forms.ModelChoiceField(
        queryset=User.objects.filter(userprofile__user_type='landlord'),
        widget=forms.HiddenInput()
    )
    landlord_search = forms.CharField(
        label='Landlord',
        widget=forms.TextInput(attrs={
            'placeholder': 'Type landlord name, username, or email...',
            'autocomplete': 'off',
            'class': 'landlord-search-input'
        }),
        required=True
    )

    class Meta:
        model = Property
        fields = [
            'owner', 'name', 'address', 'district', 'property_type',
            'num_units', 'num_flats', 'latitude', 'longitude',
            'main_image', 'image_1', 'image_2', 'image_3',
            'image_4', 'image_5', 'image_6', 'notes'
        ]
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 3}),
            'latitude': forms.HiddenInput(),
            'longitude': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['owner'].required = True
        self.fields['landlord_search'].required = False

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get('owner'):
            raise forms.ValidationError("Please select a valid landlord.")
        prop_type = cleaned_data.get('property_type')
        num_flats = cleaned_data.get('num_flats')
        if prop_type == 'residential' and not num_flats:
            self.add_error('num_flats', 'Number of flats is required for residential properties.')
        return cleaned_data


# ====================================================================
# NEW: OTP verification form
# ====================================================================
class OTPVerificationForm(forms.Form):
    otp_code = forms.CharField(
        max_length=6, min_length=6, required=True,
        widget=forms.TextInput(attrs={
            'placeholder': '000000',
            'inputmode': 'numeric',
            'maxlength': '6',
        }),
        label='OTP Code'
    )

    def clean_otp_code(self):
        code = self.cleaned_data.get('otp_code', '').strip()
        if not code.isdigit():
            raise forms.ValidationError('Must contain only digits.')
        return code
    
    # ====================================================================
# NEW: Forgot Password forms
# ====================================================================
class ForgotPasswordForm(forms.Form):
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'placeholder': 'Enter your email address',
            'autocomplete': 'email',
        }),
        label='Email Address'
    )


class ForgotPasswordOTPForm(forms.Form):
    otp_code = forms.CharField(
        max_length=6, min_length=6, required=True,
        widget=forms.TextInput(attrs={
            'placeholder': '000000',
            'inputmode': 'numeric',
            'maxlength': '6',
        }),
        label='Enter OTP Code'
    )

    def clean_otp_code(self):
        code = self.cleaned_data.get('otp_code', '').strip()
        if not code.isdigit():
            raise forms.ValidationError('Must contain only digits.')
        return code


class ResetPasswordForm(forms.Form):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'placeholder': 'Enter new password',
            'autocomplete': 'new-password',
        }),
        label='New Password',
        help_text='At least 8 characters with uppercase, lowercase, and numbers.'
    )
    password_confirm = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'placeholder': 'Confirm new password',
            'autocomplete': 'new-password',
        }),
        label='Confirm Password'
    )

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')
        if password and password_confirm and password != password_confirm:
            self.add_error('password_confirm', 'Passwords do not match.')
        from django.contrib.auth.password_validation import validate_password
        if password:
            try:
                validate_password(password)
            except forms.ValidationError as e:
                self.add_error('password', e)
        return cleaned_data