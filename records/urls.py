from django.urls import path
from . import views
from .views import (
    waste_list,
    edit_record,
    delete_record,
    login_view,
    logout_view,
    waste_graphs,
    building_status,
    generate_report,
    admin_dashboard,
    admin_reports
    ThresholdSettings,
    ResponseGuidelines
)

urlpatterns = [
    path('setup-admin/', views.setup_admin, name='setup_admin'),

    path('', login_view, name='login'),

    ##ADMIN DASHBOARD
    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),

    ##DEAN DASBOARD
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

    ##KAY ALDWIN HAHAHA
    path('waste-list/', waste_list, name='waste_list'),

    path('edit/<int:id>/', edit_record, name='edit_record'),
    path('delete/<int:id>/', delete_record, name='delete_record'),

    path('graphs/', waste_graphs, name='waste_graphs'),
    path('area-monitoring/', building_status, name='building_status'),
    path('report/', generate_report, name='generate_report'),

    path('logout/', logout_view, name='logout'),
]