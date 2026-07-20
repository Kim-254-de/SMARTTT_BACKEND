# Notifications App — Backend Integration Instructions

## 1. Create the app folder
Copy the entire `notifications/` folder into your backend at:
```
apps/notifications/
```
So the structure is:
```
apps/notifications/__init__.py
apps/notifications/admin.py
apps/notifications/apps.py
apps/notifications/fcm_service.py
apps/notifications/models.py
apps/notifications/serializers.py
apps/notifications/urls.py
apps/notifications/views.py
```

## 2. Add to INSTALLED_APPS in config/settings/base.py
Add this line alongside the other apps:
```python
"apps.notifications",
```

## 3. Add URL in config/urls.py
Add this line to urlpatterns:
```python
path("api/v1/notifications/", include("apps.notifications.urls")),
```

## 4. Install google-auth package
Add to requirements.txt:
```
google-auth==2.40.3
```

## 5. Add environment variables on Render
Go to Render Dashboard → your web service → Environment and add:

| Key | Value |
|-----|-------|
| FIREBASE_PROJECT_ID | smart-timetable-8f116 |
| FIREBASE_SERVICE_ACCOUNT_JSON | (contents of service account JSON — see step 6) |

## 6. Get Firebase service account JSON
- Go to Firebase Console → Project Settings → Service Accounts
- Click "Generate new private key"
- Download the JSON file
- Open it, copy ALL the contents
- Paste as the value of FIREBASE_SERVICE_ACCOUNT_JSON on Render
  (Render handles multi-line env vars — paste the raw JSON)

## 7. Run migrations
```bash
python manage.py makemigrations notifications
python manage.py migrate
```

## 8. Commit and push
```bash
git add apps/notifications/ config/settings/base.py config/urls.py requirements.txt
git commit -m "Add notifications app with FCM push support"
git push
```

Render will auto-deploy and run migrations via the build command.
