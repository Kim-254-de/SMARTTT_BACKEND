from rest_framework import serializers

from apps.timetable.models import AcademicTerm, TimetableConflict, TimetableSlot, TimetableUploadBatch


class AcademicTermSerializer(serializers.ModelSerializer):
    class Meta:
        model = AcademicTerm
        fields = "__all__"


class TimetableUploadBatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = TimetableUploadBatch
        fields = "__all__"
        read_only_fields = ["status", "rows_received", "rows_saved", "validation_errors"]


class TimetableSlotSerializer(serializers.ModelSerializer):
    class Meta:
        model = TimetableSlot
        fields = "__all__"


class TimetableConflictSerializer(serializers.ModelSerializer):
    class Meta:
        model = TimetableConflict
        fields = "__all__"
