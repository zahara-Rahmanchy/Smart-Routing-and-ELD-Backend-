from rest_framework import serializers
from .models import LogSheet

class LogSheetSerializer(serializers.ModelSerializer):
    class Meta:
        model = LogSheet
        fields = '__all__'
