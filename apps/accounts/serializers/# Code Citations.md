# Code Citations

## License: MIT
https://github.com/student-inbody-kiosk/ATIBO/blob/119ae6990c9f7527a86b50fe772c374ca7fb7b30/backend/apps/accounts/serializers.py

```
I found a **syntax error** in `password_change_serializer.py` that needs fixing. The `save()` method is incorrectly nested inside `validate()`, and there's unreachable code. 

Here's the corrected version:

```python
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from apps.accounts.models import User


class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True, required=True)
    new_password = serializers.CharField(write_only=True, required=True)
    confirm_password = serializers.CharField(write_only=True, required=True)

    def validate_old_password(self, value):
        """Verify the old password is correct."""
        user = self.context["request"].user
```


## License: MIT
https://github.com/student-inbody-kiosk/ATIBO/blob/119ae6990c9f7527a86b50fe772c374ca7fb7b30/backend/apps/accounts/serializers.py

```
I found a **syntax error** in `password_change_serializer.py` that needs fixing. The `save()` method is incorrectly nested inside `validate()`, and there's unreachable code. 

Here's the corrected version:

```python
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from apps.accounts.models import User


class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True, required=True)
    new_password = serializers.CharField(write_only=True, required=True)
    confirm_password = serializers.CharField(write_only=True, required=True)

    def validate_old_password(self, value):
        """Verify the old password is correct."""
        user = self.context["request"].user
```

