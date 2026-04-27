from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    # Conecta con las URLs de tu app 'logs'
    path('api/logs/', include('logs.urls')), 
]