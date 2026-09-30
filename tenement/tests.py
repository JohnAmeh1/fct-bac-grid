from io import BytesIO

from openpyxl import Workbook
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from PIL import Image
from django.contrib.auth.models import User

import uuid
from decimal import Decimal

from tenement.models import Property, USER_TYPE_CHOICES, PaymentRate, Payment, UserProfile
from tenement.views import (
    get_paginator_page_range,
    import_properties_from_uploaded_file,
    is_property_fully_paid,
    is_property_sanitation_paid,
)


class AdminRateListTests(TestCase):
    def test_admin_rate_list_page_is_available_and_lists_unpaid_rate_defaulters(self):
        admin = User.objects.create_user(
            username='admin-rate-list',
            email='admin-rate-list@example.com',
            password='StrongPass123!',
            is_staff=True,
        )
        from tenement.models import UserProfile
        UserProfile.objects.create(user=admin, user_type='admin', email_verified=True)

        landlord = User.objects.create_user(
            username='rate-landlord',
            email='rate-landlord@example.com',
            password='StrongPass123!'
        )
        UserProfile.objects.create(user=landlord, user_type='landlord', email_verified=True)

        property_obj = Property.objects.create(
            owner=landlord,
            name='Rate Property',
            address='No. 2 Market Road',
            district='Bwari',
            property_type='residential',
            num_units=4,
        )

        rate = PaymentRate.objects.create(
            property_type='residential',
            name='Annual Residential Tenement Rate 2025',
            amount='25000.00',
            is_active=True,
            is_per_unit=False,
        )

        self.client.force_login(admin)
        response = self.client.get(reverse('admin_rate_defaulters'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Rate List')
        self.assertContains(response, 'Rate Property')
        self.assertContains(response, 'Annual Residential Tenement Rate 2025')

class BulkImportAccountTests(TestCase):
    def test_user_type_choices_do_not_include_tenant(self):
        values = [choice[0] for choice in USER_TYPE_CHOICES]
        self.assertNotIn('tenant', values)
        self.assertIn('landlord', values)
        self.assertIn('staff', values)
        self.assertIn('admin', values)

    def test_csv_import_creates_property_owner_account(self):
        csv_data = (
            "Property Name,Address,District,Property Type,Latitude,Longitude\n"
            "Bwari Plaza,No. 1 Main Road,Bwari,residential,9.288472,7.390101\n"
        )
        uploaded_file = SimpleUploadedFile(
            'properties.csv',
            csv_data.encode('utf-8'),
            content_type='text/csv',
        )

        created_count, account_rows, type_summary = import_properties_from_uploaded_file(uploaded_file)

        self.assertEqual(created_count, 1)
        self.assertEqual(User.objects.filter(userprofile__user_type='landlord').count(), 1)
        self.assertTrue(Property.objects.filter(name='Bwari Plaza').exists())
        self.assertEqual(len(account_rows), 1)
        self.assertIn('username', account_rows[0])
        self.assertIn('email', account_rows[0])
        self.assertIn('password', account_rows[0])
        self.assertIn('@', account_rows[0]['email'])

    def test_real_property_enumeration_file_is_accepted(self):
        csv_data = (
            "BAC_GRID_ID,Zone,Latitude,Longitude,Approx_Footprint_m2,Status\n"
            "BAC-000001,NW,9.262377,7.3279076,90.1,NOT VISITED\n"
            "BAC-000002,SW,9.2593148,7.32877,25.1,NOT VISITED\n"
        )
        uploaded_file = SimpleUploadedFile(
            'BAC_GRID_Bwari_Property_Enumeration_Master.csv',
            csv_data.encode('utf-8'),
            content_type='text/csv',
        )

        created_count, account_rows, type_summary = import_properties_from_uploaded_file(uploaded_file)

        self.assertEqual(created_count, 2)
        self.assertEqual(len(account_rows), 2)
        self.assertTrue(Property.objects.filter(name__startswith='BAC-').exists())
        self.assertEqual(User.objects.filter(userprofile__user_type='landlord').count(), 2)

    def test_bulk_property_id_column_is_used_as_property_identifier(self):
        csv_data = (
            "No.,Bulk Property ID,Zone,Latitude,Longitude,Approx. Footprint (m²),Property Value Class,Development Score\n"
            "1,L5ZE6,NW,9.2512826,7.3554834,54.6,C - Basic,27.8\n"
            "2,R095C,NW,9.2519678,7.3536488,23.4,D - Very basic / small structure,5.5\n"
        )
        uploaded_file = SimpleUploadedFile(
            'bulk-property-import.csv',
            csv_data.encode('utf-8'),
            content_type='text/csv',
        )

        created_count, account_rows, type_summary = import_properties_from_uploaded_file(uploaded_file)

        self.assertEqual(created_count, 2)
        self.assertTrue(Property.objects.filter(name='L5ZE6').exists())
        self.assertTrue(Property.objects.filter(name='R095C').exists())
        self.assertEqual(len(account_rows), 2)
        self.assertTrue(all('L5ZE6' in row['property_name'] or 'R095C' in row['property_name'] for row in account_rows))

    def test_property_type_is_read_from_sheet_not_defaulted(self):
        csv_data = (
            "No.,Bulk Property ID,Zone,Latitude,Longitude,Property Type\n"
            "1,COM001,NW,9.2512826,7.3554834,Commercial\n"
            "2,RES001,NW,9.2519678,7.3536488,Residential\n"
        )
        uploaded_file = SimpleUploadedFile(
            'typed-properties.csv',
            csv_data.encode('utf-8'),
            content_type='text/csv',
        )

        created_count, account_rows, type_summary = import_properties_from_uploaded_file(uploaded_file)

        self.assertEqual(created_count, 2)
        self.assertEqual(Property.objects.get(name='COM001').property_type, 'commercial')
        self.assertEqual(Property.objects.get(name='RES001').property_type, 'residential')
        self.assertEqual(type_summary['commercial'], 1)
        self.assertEqual(type_summary['residential'], 1)
        self.assertEqual(type_summary['property_type_column'], 2)
        self.assertEqual(type_summary['defaulted'], 0)

    def test_property_type_falls_back_to_commercial_likelihood_column(self):
        csv_data = (
            "No.,Bulk Property ID,Zone,Latitude,Longitude,Commercial Likelihood\n"
            "1,W5X6C,NW,9.256713,7.362381,Potential commercial - footprint/development indicators\n"
            "2,R095C,NW,9.2519678,7.3536488,\n"
        )
        uploaded_file = SimpleUploadedFile(
            'commercial-likelihood.csv',
            csv_data.encode('utf-8'),
            content_type='text/csv',
        )

        created_count, account_rows, type_summary = import_properties_from_uploaded_file(uploaded_file)

        self.assertEqual(created_count, 2)
        self.assertEqual(Property.objects.get(name='W5X6C').property_type, 'commercial')
        self.assertEqual(Property.objects.get(name='R095C').property_type, 'residential')
        self.assertEqual(type_summary['commercial_likelihood_column'], 1)
        self.assertEqual(type_summary['defaulted'], 1)

    def test_same_uploaded_file_is_not_imported_twice(self):
        csv_data = (
            "BAC_GRID_ID,Zone,Latitude,Longitude,Approx_Footprint_m2,Status\n"
            "BAC-000001,NW,9.262377,7.3279076,90.1,NOT VISITED\n"
            "BAC-000002,SW,9.2593148,7.32877,25.1,NOT VISITED\n"
        )

        first_upload = SimpleUploadedFile(
            'BAC_GRID_Bwari_Property_Enumeration_Master.csv',
            csv_data.encode('utf-8'),
            content_type='text/csv',
        )
        second_upload = SimpleUploadedFile(
            'BAC_GRID_Bwari_Property_Enumeration_Master.csv',
            csv_data.encode('utf-8'),
            content_type='text/csv',
        )

        first_count, _, _ = import_properties_from_uploaded_file(first_upload)
        second_count, _, _ = import_properties_from_uploaded_file(second_upload)

        self.assertEqual(first_count, 2)
        self.assertEqual(second_count, 0)
        self.assertEqual(Property.objects.count(), 2)
        self.assertEqual(User.objects.filter(userprofile__user_type='landlord').count(), 2)

    def test_xlsx_import_with_blank_password_uses_default_password(self):
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.append([
            'Property Name', 'Address', 'District', 'Property Type',
            'Latitude', 'Longitude', 'Password'
        ])
        worksheet.append([
            'Bwari Plaza', 'No. 1 Main Road', 'Bwari', 'residential',
            '9.288472', '7.390101', None,
        ])

        buffer = BytesIO()
        workbook.save(buffer)
        uploaded_file = SimpleUploadedFile(
            'properties.xlsx',
            buffer.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )

        created_count, account_rows, type_summary = import_properties_from_uploaded_file(uploaded_file)

        self.assertEqual(created_count, 1)
        self.assertEqual(len(account_rows), 1)
        user = User.objects.get(username__startswith='bwari-plaza')
        self.assertTrue(user.check_password('12345678'))
        self.assertEqual(user.userprofile.user_type, 'landlord')

    def test_paginator_page_range_is_visible_beyond_three_pages(self):
        page = type('PageStub', (), {'number': 10, 'paginator': type('PaginatorStub', (), {'num_pages': 25, 'page_range': range(1, 26)})()})()

        page_range = get_paginator_page_range(page, siblings=2, boundary=1)

        self.assertEqual(page_range[0], 1)
        self.assertIn('…', page_range)
        self.assertEqual(page_range[-1], 25)
        self.assertGreater(len(page_range), 7)
        self.assertIn(10, page_range)

    def test_field_staff_can_create_property(self):
        field_staff = User.objects.create_user(
            username='fieldstaff1',
            email='fieldstaff1@example.com',
            password='StrongPass123!',
            is_staff=True,
        )
        from tenement.models import UserProfile
        UserProfile.objects.create(
            user=field_staff,
            user_type='field_staff',
            phone_number='08030000000',
            address='Bwari',
            email_verified=True,
        )

        self.client.force_login(field_staff)
        image_buffer = BytesIO()
        Image.new('RGB', (1, 1), color='white').save(image_buffer, format='PNG')
        png_bytes = image_buffer.getvalue()

        response = self.client.post(
            reverse('register_property'),
            {
                'name': 'Field Staff Property',
                'address': 'No. 12 Staff Road, Bwari',
                'district': 'bwari',
                'property_type': 'residential',
                'num_units': '4',
                'num_flats': '4',
                'main_image': SimpleUploadedFile('main.png', png_bytes, content_type='image/png'),
                'image_1': SimpleUploadedFile('img1.png', png_bytes, content_type='image/png'),
                'image_2': SimpleUploadedFile('img2.png', png_bytes, content_type='image/png'),
                'image_3': SimpleUploadedFile('img3.png', png_bytes, content_type='image/png'),
                'notes': 'Created by field staff',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Property.objects.filter(name='Field Staff Property').exists())
        prop = Property.objects.get(name='Field Staff Property')
        self.assertEqual(prop.owner, field_staff)

    def test_field_staff_cannot_bulk_import_properties(self):
        field_staff = User.objects.create_user(
            username='fieldstaff_import_block',
            email='fieldstaff_import_block@example.com',
            password='StrongPass123!',
            is_staff=True,
        )
        from tenement.models import UserProfile
        UserProfile.objects.create(
            user=field_staff,
            user_type='field_staff',
            email_verified=True,
        )

        csv_data = (
            "Property Name,Address,District,Property Type,Latitude,Longitude\n"
            "Blocked Import,No. 9 Field Road,Bwari,residential,9.288472,7.390101\n"
        )
        uploaded_file = SimpleUploadedFile(
            'properties.csv',
            csv_data.encode('utf-8'),
            content_type='text/csv',
        )

        self.client.force_login(field_staff)
        response = self.client.post(
            reverse('staff_import_properties'),
            {'file': uploaded_file},
            follow=True,
        )

        self.assertIn(response.status_code, (200, 302))
        self.assertFalse(Property.objects.filter(name='Blocked Import').exists())
        self.assertEqual(User.objects.filter(username='blocked-import').count(), 0)

    def test_imported_property_credentials_use_required_default_password(self):
        csv_data = (
            "Property Name,Address,District,Property Type,Latitude,Longitude\n"
            "Bwari Plaza,No. 1 Main Road,Bwari,residential,9.288472,7.390101\n"
            "Bwari Market,No. 2 Market Road,Bwari,commercial,9.298472,7.400101\n"
        )
        uploaded_file = SimpleUploadedFile(
            'properties.csv',
            csv_data.encode('utf-8'),
            content_type='text/csv',
        )

        import_properties_from_uploaded_file(uploaded_file)
        first_user = User.objects.get(username__startswith='bwari-plaza')
        second_user = User.objects.get(username__startswith='bwari-market')

        self.assertTrue(first_user.check_password('12345678'))
        self.assertTrue(second_user.check_password('12345678'))
        self.assertTrue(self.client.login(username=first_user.username, password='12345678'))

    def test_property_status_defaults_to_pending_when_no_active_rates_exist(self):
        landlord = User.objects.create_user(
            username='pending_landlord',
            email='pending_landlord@example.com',
            password='StrongPass123!'
        )
        from tenement.models import UserProfile
        UserProfile.objects.create(user=landlord, user_type='landlord', email_verified=True)

        prop = Property.objects.create(
            owner=landlord,
            name='No Rate Property',
            address='No. 32 Pending Street',
            district='bwari',
            property_type='residential',
            num_units=2,
            latitude=9.100000,
            longitude=7.200000,
        )

        self.assertFalse(is_property_fully_paid(prop))
        self.assertFalse(is_property_sanitation_paid(prop))

    def test_field_staff_sees_edit_button_on_property_view(self):
        landlord = User.objects.create_user(
            username='landlord_for_view',
            email='landlord_for_view@example.com',
            password='StrongPass123!'
        )
        from tenement.models import UserProfile
        UserProfile.objects.create(user=landlord, user_type='landlord', email_verified=True)

        field_staff = User.objects.create_user(
            username='fieldstaff_viewer',
            email='fieldstaff_viewer@example.com',
            password='StrongPass123!'
        )
        UserProfile.objects.create(user=field_staff, user_type='field_staff', email_verified=True)

        prop = Property.objects.create(
            owner=landlord,
            name='Edit Visible Property',
            address='No. 8 View Town',
            district='bwari',
            property_type='residential',
            num_units=2,
            latitude=9.100000,
            longitude=7.200000,
        )

        self.client.force_login(field_staff)
        response = self.client.get(reverse('view_property', args=[prop.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Edit Property')

    def test_field_staff_sees_edit_action_on_property_list(self):
        landlord = User.objects.create_user(
            username='landlord_for_field_list',
            email='landlord_for_field_list@example.com',
            password='StrongPass123!'
        )
        from tenement.models import UserProfile
        UserProfile.objects.create(user=landlord, user_type='landlord', email_verified=True)

        field_staff = User.objects.create_user(
            username='fieldstaff_list_editor',
            email='fieldstaff_list_editor@example.com',
            password='StrongPass123!'
        )
        UserProfile.objects.create(user=field_staff, user_type='field_staff', email_verified=True)

        prop = Property.objects.create(
            owner=landlord,
            name='List Edit Property',
            address='No. 18 List Lane',
            district='bwari',
            property_type='residential',
            num_units=2,
            latitude=9.100000,
            longitude=7.200000,
        )

        self.client.force_login(field_staff)
        response = self.client.get(reverse('admin_manage_properties'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Edit Property')
        self.assertContains(response, reverse('edit_property', args=[prop.id]))

    def test_field_staff_can_edit_property(self):
        admin_user = User.objects.create_user(
            username='fieldstaffeditor',
            email='fieldstaffeditor@example.com',
            password='StrongPass123!',
            is_staff=True,
        )
        from tenement.models import UserProfile
        UserProfile.objects.create(
            user=admin_user,
            user_type='field_staff',
            email_verified=True,
        )

        landlord = User.objects.create_user(
            username='landlord_for_field_edit',
            email='landlord_for_field_edit@example.com',
            password='StrongPass123!',
        )
        UserProfile.objects.create(
            user=landlord,
            user_type='landlord',
            email_verified=True,
        )

        property_obj = Property.objects.create(
            owner=landlord,
            name='Rural Housing',
            address='No. 10 Field Road',
            district='bwari',
            property_type='residential',
            num_units=2,
            latitude=9.100000,
            longitude=7.200000,
            notes='Original notes',
        )

        image_buffer = BytesIO()
        Image.new('RGB', (1, 1), color='white').save(image_buffer, format='PNG')
        png_bytes = image_buffer.getvalue()

        self.client.force_login(admin_user)
        response = self.client.post(
            reverse('edit_property', args=[property_obj.id]),
            {
                'name': 'Updated Field Housing',
                'address': 'No. 11 Field Road',
                'district': 'bwari',
                'property_type': 'residential',
                'num_units': '3',
                'num_flats': '3',
                'notes': 'Updated by field staff',
                'main_image': SimpleUploadedFile('main.png', png_bytes, content_type='image/png'),
                'image_1': SimpleUploadedFile('img1.png', png_bytes, content_type='image/png'),
                'image_2': SimpleUploadedFile('img2.png', png_bytes, content_type='image/png'),
                'image_3': SimpleUploadedFile('img3.png', png_bytes, content_type='image/png'),
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        property_obj.refresh_from_db()
        self.assertEqual(property_obj.name, 'Updated Field Housing')
        self.assertEqual(property_obj.address, 'No. 11 Field Road')

    def test_admin_can_create_verified_landlord_account(self):
        admin_user = User.objects.create_user(
            username='admincreator',
            email='admincreator@example.com',
            password='StrongPass123!',
            is_staff=True,
        )
        from tenement.models import UserProfile
        if not hasattr(admin_user, 'userprofile'):
            UserProfile.objects.create(
                user=admin_user,
                user_type='admin',
                email_verified=True,
            )
        else:
            admin_user.userprofile.user_type = 'admin'
            admin_user.userprofile.email_verified = True
            admin_user.userprofile.save(update_fields=['user_type', 'email_verified'])

        self.client.force_login(admin_user)
        response = self.client.post(
            reverse('admin_create_user'),
            {
                'username': 'newlandlord',
                'email': 'newlandlord@example.com',
                'first_name': 'Fresh',
                'last_name': 'Landlord',
                'phone_number': '08031234567',
                'address': 'Bwari',
                'password1': 'StrongPass123!',
                'password2': 'StrongPass123!',
                'user_type': 'landlord',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(username='newlandlord').exists())
        created_user = User.objects.get(username='newlandlord')
        self.assertEqual(created_user.userprofile.user_type, 'landlord')
        self.assertTrue(created_user.userprofile.email_verified)


class LandlordDeleteRestrictionsTests(TestCase):
    def setUp(self):
        self.landlord = User.objects.create_user(
            username='landlord-no-delete',
            email='landlord-no-delete@example.com',
            password='StrongPass123!',
        )
        UserProfile.objects.create(user=self.landlord, user_type='landlord', email_verified=True)

        self.property_obj = Property.objects.create(
            owner=self.landlord,
            name='No Delete Property',
            address='No. 5 Restriction Street',
            district='bwari',
            property_type='residential',
            num_units=2,
        )

    def test_landlord_cannot_delete_property_even_with_direct_post(self):
        self.client.force_login(self.landlord)

        response = self.client.post(
            reverse('delete_property', args=[self.property_obj.id]),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Property.objects.filter(id=self.property_obj.id).exists())
        self.assertContains(response, 'Landlord accounts are not allowed to delete properties.')

    def test_landlord_profile_hides_delete_account_action(self):
        self.client.force_login(self.landlord)

        response = self.client.get(reverse('profile'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Delete Account')

    def test_staff_cannot_delete_user(self):
        staff_user = User.objects.create_user(
            username='staff-no-delete',
            email='staff-no-delete@example.com',
            password='StrongPass123!',
            is_staff=True,
        )
        UserProfile.objects.create(user=staff_user, user_type='staff', email_verified=True)
        self.client.force_login(staff_user)

        response = self.client.post(
            reverse('admin_delete_user', args=[self.landlord.id]),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(id=self.landlord.id).exists())
        self.assertContains(response, 'Only administrators can delete users.')

    def test_dark_mode_toggle_works_from_property_page(self):
        self.client.force_login(self.landlord)

        response = self.client.post(
            reverse('toggle_dark_mode'),
            {'next': reverse('view_property', args=[self.property_obj.id])},
        )

        self.assertRedirects(response, reverse('view_property', args=[self.property_obj.id]))
        self.landlord.userprofile.refresh_from_db()
        self.assertTrue(self.landlord.userprofile.dark_mode)

        response = self.client.get(reverse('view_property', args=[self.property_obj.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'body class="app-shell page-view_property is-authenticated theme-dark')
        self.assertContains(response, 'class="theme-toggle"')


class MapsGisAccessTests(TestCase):
    """Access control: only admin/staff/field_staff can reach the Maps & GIS page and its data feed."""

    def setUp(self):
        self.admin = User.objects.create_user(username='gis-admin', password='StrongPass123!')
        UserProfile.objects.create(user=self.admin, user_type='admin', email_verified=True)

        self.staff = User.objects.create_user(username='gis-staff', password='StrongPass123!')
        UserProfile.objects.create(user=self.staff, user_type='staff', email_verified=True)

        self.field_staff = User.objects.create_user(username='gis-field-staff', password='StrongPass123!')
        UserProfile.objects.create(user=self.field_staff, user_type='field_staff', email_verified=True)

        self.landlord = User.objects.create_user(username='gis-landlord', password='StrongPass123!')
        UserProfile.objects.create(user=self.landlord, user_type='landlord', email_verified=True)

    def test_admin_staff_and_field_staff_can_view_the_page(self):
        for user in (self.admin, self.staff, self.field_staff):
            self.client.force_login(user)
            response = self.client.get(reverse('maps_gis'))
            self.assertEqual(response.status_code, 200, f'{user.username} should be able to open Maps & GIS')
            response = self.client.get(reverse('maps_gis_data'))
            self.assertEqual(response.status_code, 200, f'{user.username} should be able to read Maps & GIS data')
            self.client.logout()

    def test_landlord_cannot_access_maps_gis(self):
        self.client.force_login(self.landlord)
        response = self.client.get(reverse('maps_gis'))
        self.assertNotEqual(response.status_code, 200)
        response = self.client.get(reverse('maps_gis_data'))
        self.assertNotEqual(response.status_code, 200)

    def test_anonymous_user_cannot_access_maps_gis(self):
        response = self.client.get(reverse('maps_gis'))
        self.assertNotEqual(response.status_code, 200)
        response = self.client.get(reverse('maps_gis_data'))
        self.assertNotEqual(response.status_code, 200)


class MapsGisDataStatusTests(TestCase):
    """Verifies the red/yellow/green classification returned by the Maps & GIS data feed."""

    def setUp(self):
        self.admin = User.objects.create_user(username='gis-status-admin', password='StrongPass123!')
        UserProfile.objects.create(user=self.admin, user_type='admin', email_verified=True)

        self.landlord = User.objects.create_user(username='gis-status-landlord', password='StrongPass123!')
        UserProfile.objects.create(user=self.landlord, user_type='landlord', email_verified=True)

        self.tenement_rate = PaymentRate.objects.create(
            property_type='residential',
            name='Annual Residential Tenement Rate',
            amount=Decimal('10000.00'),
            is_active=True,
        )
        self.sanitation_rate = PaymentRate.objects.create(
            name='Monthly Sanitation Levy',
            amount=Decimal('1000.00'),
            is_active=True,
            is_sanitation=True,
        )

        # Unpaid both -> red
        self.prop_unpaid = Property.objects.create(
            owner=self.landlord, name='Unpaid Property', address='1 Test Rd', district='Bwari',
            property_type='residential', latitude=Decimal('9.251283'), longitude=Decimal('7.355483'),
        )
        # Tenement only -> yellow
        self.prop_tenement_only = Property.objects.create(
            owner=self.landlord, name='Tenement Only Property', address='2 Test Rd', district='Bwari',
            property_type='residential', latitude=Decimal('9.252000'), longitude=Decimal('7.356000'),
        )
        # Sanitation only -> yellow
        self.prop_sanitation_only = Property.objects.create(
            owner=self.landlord, name='Sanitation Only Property', address='3 Test Rd', district='Bwari',
            property_type='residential', latitude=Decimal('9.253000'), longitude=Decimal('7.357000'),
        )
        # Both paid -> green
        self.prop_fully_paid = Property.objects.create(
            owner=self.landlord, name='Fully Paid Property', address='4 Test Rd', district='Bwari',
            property_type='residential', latitude=Decimal('9.254000'), longitude=Decimal('7.358000'),
        )
        # No coordinates -> excluded from the map entirely
        self.prop_unmapped = Property.objects.create(
            owner=self.landlord, name='Unmapped Property', address='5 Test Rd', district='Bwari',
            property_type='residential',
        )

        def make_payment(prop, rate):
            Payment.objects.create(
                landlord=self.landlord,
                property=prop,
                payment_rate=rate,
                amount=rate.amount,
                reference=f'gis-test-{uuid.uuid4().hex[:10]}',
                status='success',
            )

        make_payment(self.prop_tenement_only, self.tenement_rate)
        make_payment(self.prop_sanitation_only, self.sanitation_rate)
        make_payment(self.prop_fully_paid, self.tenement_rate)
        make_payment(self.prop_fully_paid, self.sanitation_rate)

    def test_status_colors_and_summary_counts(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('maps_gis_data'))

        self.assertEqual(response.status_code, 200)
        data = response.json()

        by_id = {row[0]: row for row in data['points']}
        self.assertEqual(by_id[self.prop_unpaid.id][3], 'red')
        self.assertEqual(by_id[self.prop_tenement_only.id][3], 'yellow')
        self.assertEqual(by_id[self.prop_sanitation_only.id][3], 'yellow')
        self.assertEqual(by_id[self.prop_fully_paid.id][3], 'green')
        self.assertNotIn(self.prop_unmapped.id, by_id)

        self.assertEqual(data['summary']['total'], 4)
        self.assertEqual(data['summary']['red'], 1)
        self.assertEqual(data['summary']['yellow'], 2)
        self.assertEqual(data['summary']['green'], 1)
        self.assertEqual(data['summary']['unmapped'], 1)

# ====================================================================
# Emergency Alert System
# ====================================================================
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.test import Client, override_settings
from django.utils.html import escape

from tenement.models import Emergency, Notification, EMERGENCY_TYPES, EMERGENCY_TYPE_CHOICES


class EmergencyTestBase(TestCase):
    """Shared fixtures: one user per role, two landlords, properties with and without GPS."""

    def make_user(self, username, user_type, email=None, **profile_kwargs):
        user = User.objects.create_user(
            username=username,
            email=email if email is not None else f'{username}@example.com',
            password='StrongPass123!',
            first_name=username.split('-')[0].title(),
            last_name='Tester',
        )
        UserProfile.objects.create(user=user, user_type=user_type, email_verified=True, **profile_kwargs)
        return user

    def setUp(self):
        cache.clear()  # the report view is rate limited through the cache
        self.admin = self.make_user('admin-em', 'admin', email='admin-em@bacgrid.com')
        self.staff = self.make_user('staff-em', 'staff', email='staff-em@bacgrid.com')
        self.field_staff = self.make_user('field-em', 'field_staff', email='field-em@bacgrid.com')
        self.govt = self.make_user('govt-em', 'govt_admin', email='govt-em@bacgrid.com')
        self.landlord = self.make_user('ada-em', 'landlord', email='ada@example.com', phone_number='08030001111')
        self.other_landlord = self.make_user('bola-em', 'landlord', email='bola@example.com')

        self.prop = Property.objects.create(
            owner=self.landlord, name='Ada Court', address='12 Market Road', district='Bwari',
            property_type='residential', latitude=Decimal('9.288472'), longitude=Decimal('7.390101'),
        )
        self.prop_no_gps = Property.objects.create(
            owner=self.landlord, name='Ada Annex', address='14 Market Road', district='Bwari',
            property_type='commercial',
        )
        self.other_prop = Property.objects.create(
            owner=self.other_landlord, name='Bola Towers', address='3 Hill Street', district='Ushafa',
            property_type='residential', latitude=Decimal('9.1'), longitude=Decimal('7.2'),
        )

    def make_emergency(self, prop=None, reporter=None, emergency_type='fire', **kwargs):
        prop = prop or self.prop
        return Emergency.objects.create(
            property=prop, reported_by=reporter or prop.owner, emergency_type=emergency_type, **kwargs
        )

    def report(self, user, prop, emergency_type='fire'):
        self.client.force_login(user)
        return self.client.post(reverse('report_emergency'), {'property': prop.pk, 'emergency_type': emergency_type})


class EmergencySubmissionTests(EmergencyTestBase):
    def test_landlord_can_submit_alert_for_own_property(self):
        response = self.report(self.landlord, self.prop)
        self.assertRedirects(response, reverse('my_emergencies'))
        alert = Emergency.objects.get()
        self.assertEqual(alert.property, self.prop)
        self.assertEqual(alert.reported_by, self.landlord)
        self.assertEqual(alert.status, 'open')
        self.assertEqual(alert.emergency_type, 'fire')
        self.assertEqual(alert.message, '')
        self.assertIsNone(alert.closed_by)
        self.assertIsNone(alert.closed_at)

    def test_every_emergency_type_can_be_submitted(self):
        for key, _emoji, _name in EMERGENCY_TYPES:
            cache.clear()  # keep the rate limiter out of this loop
            Emergency.objects.all().delete()
            self.report(self.landlord, self.prop, emergency_type=key)
            self.assertEqual(Emergency.objects.get().emergency_type, key, key)

    def test_emergency_type_is_required(self):
        self.client.force_login(self.landlord)
        for payload in ({'property': self.prop.pk}, {'property': self.prop.pk, 'emergency_type': ''}):
            response = self.client.post(reverse('report_emergency'), payload)
            self.assertEqual(response.status_code, 200)
            self.assertIn('emergency_type', response.context['form'].errors)
        self.assertEqual(Emergency.objects.count(), 0)

    def test_unknown_emergency_type_is_rejected(self):
        response = self.report(self.landlord, self.prop, emergency_type='alien_invasion')
        self.assertEqual(response.status_code, 200)
        self.assertIn('emergency_type', response.context['form'].errors)
        self.assertEqual(Emergency.objects.count(), 0)

    def test_free_text_details_are_ignored(self):
        self.client.force_login(self.landlord)
        self.client.post(reverse('report_emergency'), {
            'property': self.prop.pk, 'emergency_type': 'flooding', 'message': 'typed details',
        })
        self.assertEqual(Emergency.objects.get().message, '')

    def test_report_page_has_type_dropdown_and_no_details_box(self):
        self.client.force_login(self.landlord)
        response = self.client.get(reverse('report_emergency'))
        self.assertContains(response, 'name="emergency_type"')
        self.assertNotContains(response, 'name="message"')
        self.assertNotContains(response, '<textarea')
        for _key, label in EMERGENCY_TYPE_CHOICES:
            self.assertContains(response, label)

    def test_dropdown_lists_the_eleven_types_in_order(self):
        labels = [label for _key, label in EMERGENCY_TYPE_CHOICES]
        self.assertEqual(labels, [
            '🔥 Fire Outbreak', '🔫 Armed Robbery', '🏠 Theft / Burglary', '⚠️ Murder', '🚨 Kidnapping',
            '🚗 Road Traffic Accident', '🏗️ Building Collapse', '🌊 Flooding',
            '💥 Gas Explosion / Gas Leak', '🏥 Medical Emergency', '🏠 Domestic Violence',
        ])

    def test_report_page_only_offers_the_landlords_own_properties(self):
        self.client.force_login(self.landlord)
        response = self.client.get(reverse('report_emergency'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ada Court')
        self.assertContains(response, 'Ada Annex')
        self.assertNotContains(response, 'Bola Towers')

    def test_cannot_submit_for_another_landlords_property(self):
        response = self.report(self.landlord, self.other_prop)
        self.assertEqual(response.status_code, 200)  # form re-rendered with an error, not a redirect
        self.assertFalse(response.context['form'].is_valid())
        self.assertIn('property', response.context['form'].errors)
        self.assertEqual(Emergency.objects.count(), 0)

    def test_cannot_submit_without_a_property(self):
        self.client.force_login(self.landlord)
        response = self.client.post(reverse('report_emergency'), {'emergency_type': 'fire'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Emergency.objects.count(), 0)

    def test_non_landlord_roles_cannot_report(self):
        for user in (self.admin, self.staff, self.field_staff, self.govt):
            self.client.force_login(user)
            response = self.client.post(reverse('report_emergency'), {'property': self.prop.pk, 'emergency_type': 'fire'})
            self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)
        self.assertEqual(Emergency.objects.count(), 0)

    def test_anonymous_user_cannot_report(self):
        response = self.client.post(reverse('report_emergency'), {'property': self.prop.pk})
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response['Location'])
        self.assertEqual(Emergency.objects.count(), 0)

    def test_landlord_without_properties_is_sent_to_register_one(self):
        newcomer = self.make_user('new-em', 'landlord')
        self.client.force_login(newcomer)
        response = self.client.get(reverse('report_emergency'))
        self.assertRedirects(response, reverse('register_property'), fetch_redirect_response=False)

    def test_double_tap_creates_only_one_alert(self):
        self.report(self.landlord, self.prop)
        self.report(self.landlord, self.prop)
        self.assertEqual(Emergency.objects.count(), 1)

    def test_rate_limit_stops_alert_flooding(self):
        props = [self.prop, self.prop_no_gps] + [
            Property.objects.create(owner=self.landlord, name=f'Extra {i}', address='x', district='Bwari', property_type='residential')
            for i in range(3)
        ]
        for prop in props:
            self.report(self.landlord, prop)
        self.assertEqual(Emergency.objects.count(), 3)  # EMERGENCY_RATE_LIMIT


class EmergencyNotificationTests(EmergencyTestBase):
    def test_email_goes_to_admin_and_staff_with_landlord_property_and_dashboard_link(self):
        self.report(self.landlord, self.prop, emergency_type='gas_explosion')
        alert = Emergency.objects.get()

        recipients = {addr for m in mail.outbox for addr in m.to}
        self.assertEqual(recipients, {'admin-em@bacgrid.com', 'staff-em@bacgrid.com'})

        body = mail.outbox[0].body
        self.assertIn('EMERGENCY ALERT', mail.outbox[0].subject)
        self.assertIn('Ada Court', mail.outbox[0].subject)
        self.assertIn('Ada Tester', body)            # landlord name
        self.assertIn('08030001111', body)           # landlord phone
        self.assertIn('ada@example.com', body)
        self.assertIn('12 Market Road', body)        # property details
        self.assertIn('Bwari', body)
        self.assertIn('💥 Gas Explosion / Gas Leak', body)        # emergency type
        self.assertIn('Gas Explosion / Gas Leak', mail.outbox[0].subject)
        self.assertNotIn('DETAILS', body)
        self.assertIn('https://www.google.com/maps/search/?api=1&query=9.288472,7.390101', body)
        self.assertIn(f'http://testserver/management/emergencies/{alert.pk}/', body)  # dashboard link
        alert.refresh_from_db()
        self.assertTrue(alert.email_notified)

    def test_email_says_location_unavailable_without_gps(self):
        self.report(self.landlord, self.prop_no_gps)
        self.assertIn('Location unavailable', mail.outbox[0].body)
        self.assertNotIn('google.com/maps', mail.outbox[0].body)

    @override_settings(EMERGENCY_ALERT_RECIPIENTS=['duty-officer@bacgrid.com'])
    def test_configured_recipient_list_overrides_the_default(self):
        self.report(self.landlord, self.prop)
        self.assertEqual([m.to for m in mail.outbox], [['duty-officer@bacgrid.com']])

    def test_placeholder_and_blank_addresses_are_skipped(self):
        self.make_user('ghost-em', 'staff', email='ghost@bwariproperty.local')
        self.make_user('blank-em', 'staff', email='')
        self.report(self.landlord, self.prop)
        recipients = {addr for m in mail.outbox for addr in m.to}
        self.assertEqual(recipients, {'admin-em@bacgrid.com', 'staff-em@bacgrid.com'})

    def test_alert_is_saved_even_if_email_delivery_fails(self):
        with mock.patch('tenement.views.send_mail', side_effect=Exception('SMTP down')):
            response = self.report(self.landlord, self.prop)
        self.assertRedirects(response, reverse('my_emergencies'), fetch_redirect_response=False)
        alert = Emergency.objects.get()
        self.assertEqual(alert.status, 'open')
        self.assertFalse(alert.email_notified)
        # Staff still learn about it in-app, and the landlord is told the truth.
        self.assertTrue(Notification.objects.filter(user=self.staff).exists())
        follow = self.client.get(reverse('my_emergencies'))
        self.assertEqual(follow.status_code, 200)

    def test_landlord_is_warned_when_email_could_not_be_delivered(self):
        self.client.force_login(self.landlord)
        with mock.patch('tenement.views.send_mail', side_effect=Exception('SMTP down')):
            response = self.client.post(
                reverse('report_emergency'), {'property': self.prop.pk, 'emergency_type': 'fire'}, follow=True
            )
        self.assertContains(response, 'could not be delivered')

    @override_settings(EMERGENCY_ALERT_RECIPIENTS=['not-an-email'])
    def test_alert_is_saved_when_no_valid_recipient_exists(self):
        self.report(self.landlord, self.prop)
        self.assertEqual(Emergency.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 0)

    def test_in_app_notifications_reach_responders_only(self):
        self.report(self.landlord, self.prop)
        alert = Emergency.objects.get()
        for user in (self.admin, self.staff, self.field_staff):
            note = Notification.objects.get(user=user)
            self.assertIn('Ada Court', note.message)
            self.assertIn('Fire Outbreak', note.message)
            self.assertEqual(note.link, reverse('admin_view_emergency', args=[alert.pk]))
        self.assertFalse(Notification.objects.filter(user=self.govt).exists())
        self.assertFalse(Notification.objects.filter(user=self.landlord).exists())


class EmergencyPermissionTests(EmergencyTestBase):
    def test_staff_roles_can_open_the_alert_list_and_detail(self):
        alert = self.make_emergency()
        for user in (self.admin, self.staff, self.field_staff, self.govt):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse('manage_emergencies')).status_code, 200, user.username)
            self.assertEqual(
                self.client.get(reverse('admin_view_emergency', args=[alert.pk])).status_code, 200, user.username
            )

    def test_landlord_and_anonymous_cannot_open_staff_pages(self):
        alert = self.make_emergency()
        urls = [reverse('manage_emergencies'), reverse('admin_view_emergency', args=[alert.pk])]
        for url in urls:
            self.assertNotEqual(self.client.get(url).status_code, 200)  # anonymous
        self.client.force_login(self.landlord)
        for url in urls:
            self.assertNotEqual(self.client.get(url).status_code, 200)

    def test_landlord_sees_only_their_own_alerts(self):
        self.make_emergency(self.prop, emergency_type='fire')
        self.make_emergency(self.other_prop, emergency_type='flooding')
        self.client.force_login(self.landlord)
        response = self.client.get(reverse('my_emergencies'))
        self.assertContains(response, 'Fire Outbreak')
        self.assertNotContains(response, 'Flooding')

    def test_landlord_can_view_own_alert_but_not_anothers(self):
        mine = self.make_emergency(self.prop)
        theirs = self.make_emergency(self.other_prop)
        self.client.force_login(self.landlord)
        self.assertEqual(self.client.get(reverse('view_emergency', args=[mine.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('view_emergency', args=[theirs.pk])).status_code, 404)

    def test_landlord_cannot_close_another_landlords_alert(self):
        theirs = self.make_emergency(self.other_prop)
        self.client.force_login(self.landlord)
        response = self.client.post(reverse('close_emergency', args=[theirs.pk]))
        self.assertEqual(response.status_code, 404)
        theirs.refresh_from_db()
        self.assertEqual(theirs.status, 'open')

    def test_govt_admin_is_read_only(self):
        alert = self.make_emergency()
        self.client.force_login(self.govt)
        self.client.post(reverse('close_emergency', args=[alert.pk]))
        self.client.post(reverse('mark_emergency_in_progress', args=[alert.pk]))
        alert.refresh_from_db()
        self.assertEqual(alert.status, 'open')
        page = self.client.get(reverse('manage_emergencies'))
        self.assertNotContains(page, 'Close Emergency')

    def test_landlord_cannot_mark_in_progress(self):
        alert = self.make_emergency()
        self.client.force_login(self.landlord)
        self.client.post(reverse('mark_emergency_in_progress', args=[alert.pk]))
        alert.refresh_from_db()
        self.assertEqual(alert.status, 'open')

    def test_updates_reject_get_requests(self):
        alert = self.make_emergency()
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('close_emergency', args=[alert.pk])).status_code, 405)
        self.assertEqual(self.client.get(reverse('mark_emergency_in_progress', args=[alert.pk])).status_code, 405)
        alert.refresh_from_db()
        self.assertEqual(alert.status, 'open')

    def test_updates_are_csrf_protected(self):
        alert = self.make_emergency()
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.admin)
        self.assertEqual(strict.post(reverse('close_emergency', args=[alert.pk])).status_code, 403)
        strict.force_login(self.landlord)
        self.assertEqual(strict.post(reverse('close_emergency', args=[alert.pk])).status_code, 403)
        alert.refresh_from_db()
        self.assertEqual(alert.status, 'open')

    def test_next_parameter_cannot_cause_an_open_redirect(self):
        alert = self.make_emergency()
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('close_emergency', args=[alert.pk]), {'next': 'https://evil.example/phish'}
        )
        self.assertRedirects(response, reverse('manage_emergencies'), fetch_redirect_response=False)


class EmergencyStatusTests(EmergencyTestBase):
    def test_landlord_close_records_who_and_when(self):
        alert = self.make_emergency()
        self.client.force_login(self.landlord)
        response = self.client.post(reverse('close_emergency', args=[alert.pk]), {'next': 'list'})
        self.assertRedirects(response, reverse('my_emergencies'), fetch_redirect_response=False)
        alert.refresh_from_db()
        self.assertEqual(alert.status, 'closed')
        self.assertEqual(alert.closed_by, self.landlord)
        self.assertIsNotNone(alert.closed_at)
        # Responders are told the landlord closed it.
        self.assertTrue(Notification.objects.filter(user=self.staff, message__contains='closed').exists())

    def test_staff_roles_can_close_any_alert_and_the_closer_is_recorded(self):
        for user in (self.admin, self.staff, self.field_staff):
            alert = self.make_emergency()
            self.client.force_login(user)
            self.client.post(reverse('close_emergency', args=[alert.pk]), {'next': 'list', 'status': 'open'})
            alert.refresh_from_db()
            self.assertEqual(alert.status, 'closed', user.username)
            self.assertEqual(alert.closed_by, user)
            self.assertIsNotNone(alert.closed_at)

    def test_landlord_is_notified_when_staff_close_their_alert(self):
        alert = self.make_emergency()
        self.client.force_login(self.staff)
        self.client.post(reverse('close_emergency', args=[alert.pk]))
        note = Notification.objects.get(user=self.landlord)
        self.assertIn('closed', note.message)
        self.assertEqual(note.link, reverse('view_emergency', args=[alert.pk]))

    def test_staff_can_mark_in_progress_then_close(self):
        alert = self.make_emergency()
        self.client.force_login(self.staff)
        self.client.post(reverse('mark_emergency_in_progress', args=[alert.pk]))
        alert.refresh_from_db()
        self.assertEqual(alert.status, 'in_progress')
        self.assertEqual(alert.in_progress_by, self.staff)
        self.assertIsNotNone(alert.in_progress_at)
        self.assertTrue(Notification.objects.filter(user=self.landlord, message__contains='In Progress').exists())

        self.client.force_login(self.admin)
        self.client.post(reverse('close_emergency', args=[alert.pk]))
        alert.refresh_from_db()
        self.assertEqual(alert.status, 'closed')
        self.assertEqual(alert.closed_by, self.admin)
        self.assertEqual(alert.in_progress_by, self.staff)  # acknowledgement history is kept

    def test_landlord_can_close_an_in_progress_alert(self):
        alert = self.make_emergency(status='in_progress')
        self.client.force_login(self.landlord)
        self.client.post(reverse('close_emergency', args=[alert.pk]))
        alert.refresh_from_db()
        self.assertEqual(alert.status, 'closed')

    def test_closed_alert_cannot_be_reopened_or_reclosed(self):
        alert = self.make_emergency()
        self.client.force_login(self.staff)
        self.client.post(reverse('close_emergency', args=[alert.pk]))
        alert.refresh_from_db()
        first_closer, first_time = alert.closed_by, alert.closed_at

        self.client.force_login(self.admin)
        self.client.post(reverse('close_emergency', args=[alert.pk]))
        self.client.post(reverse('mark_emergency_in_progress', args=[alert.pk]))
        alert.refresh_from_db()
        self.assertEqual(alert.status, 'closed')
        self.assertEqual(alert.closed_by, first_closer)
        self.assertEqual(alert.closed_at, first_time)

    def test_list_filters_by_status(self):
        self.make_emergency(emergency_type='fire')                              # open
        self.make_emergency(emergency_type='flooding', status='in_progress')
        self.make_emergency(emergency_type='medical', status='closed')
        self.client.force_login(self.admin)

        def page(status):
            return self.client.get(reverse('manage_emergencies'), {'status': status})

        self.assertContains(page('open'), 'Fire Outbreak')
        self.assertNotContains(page('open'), 'Medical Emergency')
        self.assertContains(page('in_progress'), 'Flooding')
        self.assertContains(page('closed'), 'Medical Emergency')
        for marker in ('Fire Outbreak', 'Flooding', 'Medical Emergency'):
            self.assertContains(page('all'), marker)
        self.assertContains(page('bogus'), 'Fire Outbreak')  # unknown filter falls back to Open

    def test_status_counts_on_list_page(self):
        self.make_emergency()
        self.make_emergency(status='in_progress')
        self.make_emergency(status='closed')
        self.client.force_login(self.admin)
        response = self.client.get(reverse('manage_emergencies'))
        self.assertEqual(
            (response.context['open_count'], response.context['in_progress_count'],
             response.context['closed_count'], response.context['total_count']),
            (1, 1, 1, 3),
        )


class EmergencyMapLinkTests(EmergencyTestBase):
    EXPECTED = 'https://www.google.com/maps/search/?api=1&query=9.288472,7.390101'

    def test_map_url_uses_the_properties_actual_coordinates(self):
        self.assertEqual(self.make_emergency(self.prop).google_maps_url, self.EXPECTED)

    def test_map_url_handles_negative_coordinates(self):
        prop = Property.objects.create(
            owner=self.landlord, name='South', address='x', district='Bwari', property_type='residential',
            latitude=Decimal('-1.500000'), longitude=Decimal('-70.250000'),
        )
        self.assertIn('query=-1.500000,-70.250000', self.make_emergency(prop).google_maps_url)

    def test_map_url_is_none_when_coordinates_are_missing(self):
        self.assertIsNone(self.make_emergency(self.prop_no_gps).google_maps_url)
        half = Property.objects.create(
            owner=self.landlord, name='Half', address='x', district='Bwari', property_type='residential',
            latitude=Decimal('9.1'),
        )
        self.assertIsNone(self.make_emergency(half).google_maps_url)

    def test_list_and_detail_link_to_google_maps(self):
        alert = self.make_emergency(self.prop)
        self.client.force_login(self.staff)
        for url in (reverse('manage_emergencies'), reverse('admin_view_emergency', args=[alert.pk])):
            response = self.client.get(url)
            self.assertContains(response, f'href="{escape(self.EXPECTED)}"')
            self.assertNotContains(response, 'Location unavailable')

    def test_list_and_detail_show_location_unavailable_without_coordinates(self):
        alert = self.make_emergency(self.prop_no_gps)
        self.client.force_login(self.staff)
        for url in (reverse('manage_emergencies'), reverse('admin_view_emergency', args=[alert.pk])):
            response = self.client.get(url)
            self.assertContains(response, 'Location unavailable')
            self.assertNotContains(response, 'google.com/maps')


class EmergencyStaffPageContentTests(EmergencyTestBase):
    def test_list_shows_landlord_property_date_and_status(self):
        self.make_emergency(self.prop, emergency_type='gas_explosion')
        self.client.force_login(self.admin)
        response = self.client.get(reverse('manage_emergencies'))
        self.assertContains(response, 'Ada Tester')
        self.assertContains(response, '08030001111')
        self.assertContains(response, 'ada@example.com')
        self.assertContains(response, 'Ada Court')
        self.assertContains(response, '12 Market Road')
        self.assertContains(response, 'Gas Explosion / Gas Leak')
        self.assertContains(response, 'Open')
        self.assertContains(response, 'View details')
        self.assertContains(response, 'Close Emergency')

    def test_detail_page_shows_the_emergency_type(self):
        alert = self.make_emergency(self.prop, emergency_type='kidnapping')
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse('admin_view_emergency', args=[alert.pk])), '🚨 Kidnapping')
        self.client.force_login(self.landlord)
        self.assertContains(self.client.get(reverse('view_emergency', args=[alert.pk])), '🚨 Kidnapping')

    def test_legacy_alert_without_a_type_still_renders(self):
        alert = self.make_emergency(emergency_type='')
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse('manage_emergencies')), 'type not recorded')
        self.assertEqual(self.client.get(reverse('admin_view_emergency', args=[alert.pk])).status_code, 200)

    def test_legacy_details_are_html_escaped(self):
        self.make_emergency(message='<script>alert(1)</script>')
        self.client.force_login(self.admin)
        response = self.client.get(reverse('manage_emergencies'))
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertContains(response, '&lt;script&gt;')

    def test_closed_alert_shows_who_closed_it(self):
        alert = self.make_emergency()
        self.client.force_login(self.staff)
        self.client.post(reverse('close_emergency', args=[alert.pk]))
        response = self.client.get(reverse('manage_emergencies'), {'status': 'closed'})
        self.assertContains(response, 'Closed by Staff Tester')

    def test_placeholder_landlord_email_is_not_displayed(self):
        bulk = self.make_user('bulk-em', 'landlord', email='bulk123@bwariproperty.local')
        prop = Property.objects.create(owner=bulk, name='Bulk House', address='x', district='Bwari', property_type='residential')
        self.make_emergency(prop)
        self.client.force_login(self.admin)
        self.assertNotContains(self.client.get(reverse('manage_emergencies')), 'bwariproperty.local')


class EmergencyDashboardTests(EmergencyTestBase):
    def test_landlord_dashboard_has_a_prominent_emergency_button(self):
        self.client.force_login(self.landlord)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('report_emergency'))
        self.assertContains(response, 'Emergency at your property?')

    def test_landlord_dashboard_shows_active_alert_count(self):
        self.make_emergency()
        self.make_emergency(status='closed')
        self.client.force_login(self.landlord)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['active_emergency_count'], 1)

    def test_staff_dashboard_links_to_alerts_and_flags_open_ones(self):
        self.make_emergency()
        self.make_emergency(status='closed')
        for user in (self.admin, self.staff, self.field_staff, self.govt):
            self.client.force_login(user)
            response = self.client.get(reverse('dashboard'))
            self.assertEqual(response.status_code, 200, user.username)
            self.assertContains(response, reverse('manage_emergencies'))
            self.assertEqual(response.context['open_emergency_count'], 1)
            self.assertContains(response, '1 open emergency alert needs attention')