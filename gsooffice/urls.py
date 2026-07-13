from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from records import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('setup-admin/', views.setup_admin, name='setup_admin'),

    path('', views.login_view, name='login'),
        path('login/', views.login_view, name='login'),
        path('logout/', views.logout_view, name='logout'),

    ##ADMIN DASHBOARD
    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),

    ##DEAN DASHBOARD
    path('dean-dashboard/', views.dean_dashboard, name='dean_dashboard'),

    ##ADMIN AREA MANAGEMENT
    path('areas/', views.area_list, name='area_list'),
    path('areas/add/', views.add_area, name='add_area'),
    path('areas/edit/<int:area_id>/', views.edit_area, name='edit_area'),
    path('areas/update-status/<int:area_id>/', views.update_area_status, name='update_area_status'),

    path('areas/delete/<int:area_id>/', views.delete_area, name='delete_area'),

    ##ADMIN USER MANAGEMENT
    path('users/', views.user_list, name='user_list'),
    path('users/add/', views.add_user, name='add_user'),
    path('users/edit/<int:user_id>/', views.edit_user, name='edit_user'),
    path('users/delete/<int:user_id>/', views.delete_user, name='delete_user'),

    ##ADMIN REPORTS
    path('admin-reports/', views.admin_reports, name='admin_reports'),
    path('export-csv/', views.export_csv, name='export_csv'),

    ##ADMIN SETTINGS
    path('threshold-settings/', views.threshold_settings, name='threshold_settings'),
    path('response-guidelines/', views.response_guidelines, name='response_guidelines'),

    ##KAY ALDWIN HASGDFASHGD
    path('waste/', views.waste_list, name='waste_list'),
    path('graphs/', views.waste_graphs, name='waste_graphs'),
    path('building-status/', views.building_status, name='building_status'),
    path('report/', views.generate_report, name='generate_report'),
    path('profile/', views.edit_profile, name='edit_profile'),
    path('edit/<int:pk>/', views.edit_record, name='edit_record'),
    path('delete/<int:pk>/', views.delete_record, name='delete_record'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)