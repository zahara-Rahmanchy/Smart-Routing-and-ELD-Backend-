from django.db import models

# Create your models here.
from django.db import models
from roadmap.models import Trip

class LogSheet(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="logs")
    day_number = models.IntegerField()  # Day 1, Day 2, ...
    driving_hours = models.FloatField()
    rest_hours = models.FloatField()
    idle_hours = models.FloatField()
    distance_km = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Trip {self.trip.id} - Day {self.day_number}"
