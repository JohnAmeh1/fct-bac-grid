from django.urls import path
from . import views

urlpatterns = [
    # ── Public ────────────────────────────────────────────────
    path('', views.home, name='home'),
    path('about/', views.about, name='about'),
    path('contact/', views.contact, name='contact'),
    path('sanitation/', views.sanitation, name='sanitation'),

    # ── Auth ──────────────────────────────────────────────────
    path('accounts/signup/', views.signup_view, name='signup'),
    path('accounts/login/', views.login_view, name='login'),
    path('accounts/logout/', views.logout_view, name='logout'),

    # ── Email Verification (NEW) ─────────────────────────────
    path('verify-email/', views.verify_email, name='verify_email'),
    path('resend-otp/', views.resend_otp, name='resend_otp'),

    # ── Core ──────────────────────────────────────────────────
    path('dashboard/', views.dashboard, name='dashboard'),
    path('profile/', views.profile_view, name='profile'),
    path('profile/verify-email-change/', views.verify_email_change, name='verify_email_change'),
    path('profile/resend-email-change-otp/', views.resend_email_change_otp, name='resend_email_change_otp'),
    path('profile/cancel-email-change/', views.cancel_email_change, name='cancel_email_change'),
    path('theme/toggle/', views.toggle_dark_mode, name='toggle_dark_mode'),

    # ── Landlord: Properties ───────────────────────────────────
    path('properties/register/', views.register_property, name='register_property'),
    path('properties/', views.landlord_properties, name='landlord_properties'),
    path('properties/<int:property_id>/', views.view_property, name='view_property'),
    path('properties/<int:property_id>/edit/', views.edit_property, name='edit_property'),
    path('properties/<int:property_id>/delete/', views.delete_property, name='delete_property'),

    # ── Landlord: Complaints ───────────────────────────────────
    path('complaints/submit/', views.submit_complaint, name='submit_complaint'),
    path('complaints/', views.my_complaints, name='my_complaints'),

    # ── Admin: Users ───────────────────────────────────────────
    path('management/users/', views.admin_manage_users, name='admin_manage_users'),
    path('management/users/reset-demo-data/', views.admin_reset_demo_data, name='admin_reset_demo_data'),
    path('management/users/reset-demo-data/progress/<str:progress_key>/', views.admin_reset_demo_data_progress, name='admin_reset_demo_data_progress'),
    path('management/users/<int:user_id>/', views.admin_view_user, name='admin_view_user'),
    path('management/users/<int:user_id>/delete/', views.admin_delete_user, name='admin_delete_user'),

    # ── Admin: Properties ──────────────────────────────────────
    path('management/properties/', views.admin_manage_properties, name='admin_manage_properties'),
    path('management/properties/<int:property_id>/', views.admin_view_property, name='admin_view_property'),
    path('management/properties/<int:property_id>/delete/', views.admin_delete_property, name='admin_delete_property'),
    path('management/revenue/', views.admin_revenue_list, name='admin_revenue_list'),
    path('management/maps/', views.maps_gis, name='maps_gis'),
    path('management/maps/data/', views.maps_gis_data, name='maps_gis_data'),
    path('management/verification/', views.admin_verification_queue, name='admin_verification_queue'),
    path('management/verification/verify-all/', views.admin_verify_all_properties, name='admin_verify_all_properties'),
    path('management/verification/verify-all/progress/<str:progress_key>/', views.admin_verify_all_properties_progress, name='admin_verify_all_properties_progress'),
    path('management/verification/<int:property_id>/verify/', views.admin_verify_property, name='admin_verify_property'),
    path('management/verification/<int:property_id>/flag/', views.admin_flag_property_verification, name='admin_flag_property_verification'),

    # ── Support Tickets ─────────────────────────────────────────
    path('support/', views.my_support_tickets, name='my_support_tickets'),
    path('support/new/', views.submit_support_ticket, name='submit_support_ticket'),
    path('support/<int:ticket_id>/', views.view_support_ticket, name='view_support_ticket'),
    path('management/support/', views.admin_manage_support_tickets, name='admin_manage_support_tickets'),
    path('management/support/<int:ticket_id>/', views.admin_view_support_ticket, name='admin_view_support_ticket'),

    # ── Notifications ───────────────────────────────────────────
    path('notifications/', views.notifications_list, name='notifications_list'),
    path('notifications/mark-read/<int:notification_id>/', views.mark_notification_read, name='mark_notification_read'),
    path('notifications/mark-all-read/', views.mark_all_notifications_read, name='mark_all_notifications_read'),
    path('notifications/api/', views.get_notifications, name='get_notifications_api'),

    # ── Admin: Complaints ──────────────────────────────────────
    path('management/complaints/', views.admin_manage_complaints, name='admin_manage_complaints'),
    path('management/complaints/<int:complaint_id>/', views.admin_view_complaint, name='admin_view_complaint'),

    # ── Admin: Configuration & Export ─────────────────────────
    path('management/configuration/', views.admin_site_configuration, name='admin_site_configuration'),
    path('management/export/landlords/', views.admin_export_landlords, name='admin_export_landlords'),
    path('management/export/users/', views.admin_export_users, name='admin_export_users'),
    path('management/export/progress/<str:progress_key>/', views.export_progress, name='export_progress'),
    path('management/export/download/<str:progress_key>/', views.download_export, name='download_export'),

    # ── Admin: Payment Rates ──────────────────────────────────
    path('management/payments/rates/', views.admin_payment_rates, name='admin_payment_rates'),
    path('management/payments/rates/create/', views.admin_create_payment_rate, name='admin_create_payment_rate'),
    path('management/payments/rates/<int:rate_id>/edit/', views.admin_edit_payment_rate, name='admin_edit_payment_rate'),
    path('management/payments/rates/<int:rate_id>/delete/', views.admin_delete_payment_rate, name='admin_delete_payment_rate'),
    path('management/payments/rates/<int:rate_id>/toggle/', views.admin_toggle_payment_rate, name='admin_toggle_payment_rate'),
    path('management/payments/', views.admin_all_payments, name='admin_all_payments'),

    # Admin Announcements
    path('management/announcements/', views.admin_manage_announcements, name='admin_manage_announcements'),
    path('management/announcements/create/', views.admin_create_announcement, name='admin_create_announcement'),
    path('management/announcements/<int:announcement_id>/delete/', views.admin_delete_announcement, name='admin_delete_announcement'),
    
    # User API
    path('announcements/list/', views.get_announcements, name='get_announcements'),
    path('announcements/<int:announcement_id>/read/', views.mark_announcement_read, name='mark_announcement_read'),

    # ── Admin: Create User (staff only via admin) ──────────────
    path('management/users/create/', views.admin_create_user, name='admin_create_user'),

    # ── Admin: Pay Bypass ──────────────────────────────────────
    path('management/pay-bypass/', views.admin_pay_bypass, name='admin_pay_bypass'),
    path('management/pay-bypass/<int:property_id>/<int:rate_id>/mark-paid/', views.admin_pay_bypass_update, name='admin_pay_bypass_update'),

    # ── Admin: Defaulters ──────────────────────────────────────
    path('management/defaulters/', views.admin_defaulters_list, name='admin_defaulters_list'),
    path('management/defaulters/export/', views.admin_export_defaulters, name='admin_export_defaulters'),
    path('management/rate-defaulters/', views.admin_rate_defaulters, name='admin_rate_defaulters'),
    path('management/rate-defaulters/export/', views.admin_export_rate_defaulters, name='admin_export_rate_defaulters'),
    path('management/sanitation-defaulters/', views.admin_sanitation_defaulters, name='admin_sanitation_defaulters'),
    path('management/sanitation-defaulters/export/', views.admin_export_sanitation_defaulters, name='admin_export_sanitation_defaulters'),
    
    # ── Landlord: Payments ────────────────────────────────────
    path('payments/', views.landlord_payments, name='landlord_payments'),
    path('payments/initiate/<int:property_id>/<int:rate_id>/', views.initiate_payment, name='initiate_payment'),
    path('payments/verify/<str:reference>/', views.verify_payment, name='verify_payment'),
    path('payments/receipt/<int:payment_id>/', views.payment_receipt, name='payment_receipt'),
    path('payments/receipt/<int:payment_id>/download/', views.download_receipt_pdf, name='download_receipt_pdf'),
    path('payments/get-access-code/<int:property_id>/<int:rate_id>/', views.get_paystack_access_code, name='get_paystack_access_code'),

    # staff
    path('staff/create-landlord/', views.staff_create_landlord, name='staff_create_landlord'),
    path('staff/register-property/', views.staff_register_property, name='staff_register_property'),
    path('staff/import-properties/', views.staff_import_properties, name='staff_import_properties'),
    path('staff/import-properties/progress/<str:progress_key>/', views.staff_import_properties_progress, name='staff_import_properties_progress'),
    path('staff/search-landlords/', views.search_landlords, name='search_landlords'),
    path('staff/verify-payment/', views.staff_verify_payment, name='staff_verify_payment'),
    
    # tenant 
    path('payments/tenant/', views.tenant_payments, name='tenant_payments'),
    # ── Public Receipt Lookup (no login required) ─────────────
    path('receipt/lookup/', views.public_lookup_receipt, name='public_lookup_receipt'),

    # ── Forgot Password (NEW) ─────────────────────────────────
    path('forgot-password/', views.forgot_password, name='forgot_password'),
    path('verify-forgot-password-otp/', views.verify_forgot_password_otp, name='verify_forgot_password_otp'),
    path('reset-password/', views.reset_password, name='reset_password'),
    path('resend-forgot-password-otp/', views.resend_forgot_password_otp, name='resend_forgot_password_otp'),

    # ── Emergencies ─────────────────────────────────────────────
    path('emergency/report/', views.report_emergency, name='report_emergency'),
    path('emergency/<int:emergency_id>/close/', views.close_emergency, name='close_emergency'),
    path('management/emergencies/', views.admin_manage_emergencies, name='admin_manage_emergencies'),

    # ── Bye-Law Pages ─────────────────────────────────────────────────────────────
    path('bylaws/', views.bylaw_preliminary, name='bylaw_preliminary'),
    path('bylaws/enabling-law/', views.bylaw_enabling_law, name='bylaw_enabling_law'),
    path('bylaws/marriages-births-deaths/', views.bylaw_marriages, name='bylaw_marriages'),
    path('bylaws/motor-parks/', views.bylaw_motor_parks, name='bylaw_motor_parks'),
    path('bylaws/environmental-sanitation/', views.bylaw_environmental_sanitation, name='bylaw_environmental_sanitation'),
    
    path('bylaws/allied_matters/', views.bylaw_allied_matters, name='bylaw_allied_matters'),
    path('bylaws/borehole_drilling/', views.bylaw_borehole_drilling, name='bylaw_borehole_drilling'),
    path('bylaws/commercial_pos_operators/', views.bylaw_commercial_pos_operators, name='bylaw_commercial_pos_operators'),
    path('bylaws/community_tax/', views.bylaw_community_tax, name='bylaw_community_tax'),
    path('bylaws/construction_permits/', views.bylaw_construction_permits, name='bylaw_construction_permits'),
    path('bylaws/contractors/', views.bylaw_contractors, name='bylaw_contractors'),
    path('bylaws/control_of_advertisement/', views.bylaw_control_of_advertisement, name='bylaw_control_of_advertisement'),
    
    path('bylaws/cutting-road-tar/', views.bylaw_cutting_road_tar, name='bylaw_cutting_road_tar'),
    path('bylaws/foodstuff-regulation/', views.bylaw_foodstuff_regulation, name='bylaw_foodstuff_regulation'),
    path('bylaws/house-numbering/', views.bylaw_house_numbering, name='bylaw_house_numbering'),
    path('bylaws/liquor-licensing/', views.bylaw_liquor_licensing, name='bylaw_liquor_licensing'),
    path('bylaws/market-regulation/', views.bylaw_market_regulation, name='bylaw_market_regulation'),
    path('bylaws/mobile-advertisement/', views.bylaw_mobile_advertisement, name='bylaw_mobile_advertisement'),
    path('bylaws/motorcycle-uses/', views.bylaw_motorcycle_uses, name='bylaw_motorcycle_uses'),
    path('bylaws/movement-keeping-dogs/', views.bylaw_movement_keeping_dogs, name='bylaw_movement_keeping_dogs'),
    path('bylaws/parking-traffic-control/', views.bylaw_parking_traffic_control, name='bylaw_parking_traffic_control'),
    path('bylaws/pest-control/', views.bylaw_pest_control, name='bylaw_pest_control'),
    path('bylaws/public-toilet/', views.bylaw_public_toilet, name='bylaw_public_toilet'),
    path('bylaws/refuse-operation/', views.bylaw_refuse_operation, name='bylaw_refuse_operation'),
    path('bylaws/laundry-registration/', views.bylaw_laundry_registration, name='bylaw_laundry_registration'),
    path('bylaws/regulated-premises/', views.bylaw_regulated_premises, name='bylaw_regulated_premises'),
    path('bylaws/tenement_rate/', views.bylaw_tenement_rate, name='bylaw_tenement_rate'),
    path('bylaws/tv-license/', views.bylaw_tv_license, name='bylaw_tv_license'),
    path('bylaws/wrong-parking/', views.bylaw_wrong_parking, name='bylaw_wrong_parking'),
]