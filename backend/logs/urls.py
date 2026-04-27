from django.urls import path
from .views import calculate_logs, generate_pdf

urlpatterns = [
    path("calculate/", calculate_logs, name="calculate_logs"),
    path("generate-pdf/", generate_pdf, name="generate_pdf"),
]