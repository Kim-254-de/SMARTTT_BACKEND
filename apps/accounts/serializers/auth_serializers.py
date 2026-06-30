from rest_framework import serializers
from apps.accounts.models import User

class RegisterSerializer(serializers.Serializer):
    email           = serializers.EmailField()
    password        = serializers.CharField(write_only=True, min_length=6)
    full_name       = serializers.CharField()
    admission_number = serializers.CharField(required=False, allow_blank=True)
    course          = serializers.CharField(required=False, allow_blank=True)
    year_of_study   = serializers.IntegerField(default=1)

class LoginSerializer(serializers.Serializer):
    email    = serializers.EmailField()
    password = serializers.CharField(write_only=True)

class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    class Meta:
        model  = User
        fields = ["id","email","full_name","university_id","role"]
    def get_full_name(self, obj):
        return obj.get_full_name()
