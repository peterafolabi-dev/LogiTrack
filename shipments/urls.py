from django.urls import path
from django.contrib.auth import views as auth_views

from . import views

urlpatterns = [
    path("", views.landing, name="landing"),
    path("signup/", views.signup_view, name="signup"),
    path("login/", views.login_view, name="login"),
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="auth/password_reset_form.html",
            email_template_name="auth/password_reset_email.html",
            subject_template_name="auth/password_reset_subject.txt",
            success_url="/password-reset/done/",
        ),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="auth/password_reset_done.html",
        ),
        name="password_reset_done",
    ),
    path(
        "password-reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="auth/password_reset_confirm.html",
            success_url="/password-reset/complete/",
        ),
        name="password_reset_confirm",
    ),
    path(
        "password-reset/complete/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="auth/password_reset_complete.html",
        ),
        name="password_reset_complete",
    ),
    path("logout/", views.logout_view, name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("shipments/", views.shipments_list, name="shipments_list"),
    path("shipments/scanner/", views.barcode_scanner_view, name="barcode_scanner"),
    path("shipments/demo-telemetry/", views.populate_demo_telemetry, name="populate_demo_telemetry"),
    path("shipments/new/", views.shipment_create, name="shipment_create"),
    path("shipments/<int:pk>/", views.shipment_detail, name="shipment_detail"),
    path("shipments/<int:pk>/edit/", views.shipment_edit, name="shipment_edit"),
    path("shipments/<int:pk>/label/", views.shipment_label_pdf, name="shipment_label_pdf"),
    path("profile/", views.profile_view, name="profile"),
    path("tracking/", views.public_tracking_page, name="public_tracking"),
    path("api/track/<str:tracking_number>/", views.public_tracking_api, name="public_tracking_api"),
    path("api/shipments/batch-update/", views.batch_update_api, name="batch_update_api"),
]
