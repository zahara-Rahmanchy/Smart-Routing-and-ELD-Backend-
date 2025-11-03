from logsheet.serializers import LogSheetSerializer
from roadmap.models import Trip
from rest_framework import serializers

class TripSerializer(serializers.ModelSerializer):
    logs = LogSheetSerializer(many=True, read_only=True)
    
    class Meta:
        model = Trip
        fields = '__all__'