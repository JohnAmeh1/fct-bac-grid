from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from PIL import Image
from django.contrib.auth.models import User

from tenement.models import Property, USER_TYPE_CHOICES, PaymentRate
from tenement.views import import_properties_from_uploaded_file, is_property_fully_paid, is_property_sanitation_paid


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

        created_count, account_rows = import_properties_from_uploaded_file(uploaded_file)

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

        created_count, account_rows = import_properties_from_uploaded_file(uploaded_file)

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

        created_count, account_rows = import_properties_from_uploaded_file(uploaded_file)

        self.assertEqual(created_count, 2)
        self.assertTrue(Property.objects.filter(name='L5ZE6').exists())
        self.assertTrue(Property.objects.filter(name='R095C').exists())
        self.assertEqual(len(account_rows), 2)
        self.assertTrue(all('L5ZE6' in row['property_name'] or 'R095C' in row['property_name'] for row in account_rows))

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

        first_count, _ = import_properties_from_uploaded_file(first_upload)
        second_count, _ = import_properties_from_uploaded_file(second_upload)

        self.assertEqual(first_count, 2)
        self.assertEqual(second_count, 0)
        self.assertEqual(Property.objects.count(), 2)
        self.assertEqual(User.objects.filter(userprofile__user_type='landlord').count(), 2)

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
