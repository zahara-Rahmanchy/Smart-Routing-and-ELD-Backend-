from django.urls import path
from .views import GenerateLogSheets

urlpatterns = [
    path('generate/<int:trip_id>/', GenerateLogSheets.as_view(), name='generate_logs'),
]
