from django.utils import timezone
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.core.models import Program
from apps.courses.models import StudentUnit

from .fcm_service import send_to_tokens
from .models import FCMToken, Notification, StudentNotification
from .serializers import (
    FCMTokenSerializer, NotificationSerializer,
    SendNotificationSerializer, StudentNotificationSerializer,
)


class RegisterFCMTokenView(APIView):
    """
    POST /api/v1/notifications/register-token/
    Called by Flutter on login/app open to register/update the device token.
    Body: { "token": "...", "platform": "android"|"ios"|"web" }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        s = FCMTokenSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        token = s.validated_data["token"]
        platform = s.validated_data["platform"]

        # Update or create — one token entry per physical token value
        FCMToken.objects.update_or_create(
            token=token,
            defaults={"user": request.user, "platform": platform},
        )
        return Response({"detail": "Token registered."})


class SendNotificationView(APIView):
    """
    POST /api/v1/notifications/send/
    Admin sends a notification to all or targeted students.
    """
    permission_classes = [IsAdminUser]

    def post(self, request):
        s = SendNotificationSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data

        title = d["title"]
        message = d["message"]
        target = d["target"]
        notification_type = d.get("notification_type", Notification.Type.GENERAL)
        target_program_id = d.get("target_program")
        target_year = d.get("target_year")

        # ── Resolve target program ────────────────────────────────────────────
        target_program = None
        if target_program_id:
            try:
                target_program = Program.objects.get(pk=target_program_id)
            except Program.DoesNotExist:
                return Response({"detail": "Program not found."}, status=400)

        # ── Resolve recipient users ───────────────────────────────────────────
        if target == Notification.Target.ALL:
            users = User.objects.filter(is_active=True, role=User.Role.STUDENT)
        elif target == Notification.Target.PROGRAM and target_program:
            # Students who have units under this program
            unit_ids = target_program.timetable_slots.values_list("unit_id", flat=True)
            student_ids = StudentUnit.objects.filter(
                unit_id__in=unit_ids
            ).values_list("user_id", flat=True)
            users = User.objects.filter(id__in=student_ids, is_active=True)
        elif target == Notification.Target.YEAR and target_year:
            # Students in a specific year — we check their StudentUnit term slots
            from apps.timetable.models import TimetableSlot, AcademicTerm
            term = AcademicTerm.objects.filter(is_current=True).first()
            if not term:
                return Response({"detail": "No current academic term set."}, status=400)
            slot_unit_ids = TimetableSlot.objects.filter(
                term=term, year_of_study=target_year
            ).values_list("unit_id", flat=True)
            student_ids = StudentUnit.objects.filter(
                unit_id__in=slot_unit_ids, term=term
            ).values_list("user_id", flat=True)
            users = User.objects.filter(id__in=student_ids, is_active=True)
        else:
            users = User.objects.filter(is_active=True, role=User.Role.STUDENT)

        users = list(users)

        # ── Create Notification record ────────────────────────────────────────
        notification = Notification.objects.create(
            sent_by=request.user,
            title=title,
            message=message,
            notification_type=notification_type,
            target=target,
            target_program=target_program,
            target_year=target_year,
            recipients_count=len(users),
        )

        # ── Create StudentNotification records ────────────────────────────────
        StudentNotification.objects.bulk_create([
            StudentNotification(user=user, notification=notification)
            for user in users
        ], ignore_conflicts=True)

        # ── Send FCM push notifications ───────────────────────────────────────
        user_ids = [u.id for u in users]
        tokens = list(
            FCMToken.objects.filter(user_id__in=user_ids)
            .values_list("token", flat=True)
        )

        fcm_success = 0
        if tokens:
            fcm_success = send_to_tokens(
                tokens, title, message,
                data={"type": notification_type, "notification_id": str(notification.id)},
            )

        return Response({
            "detail": "Notification sent.",
            "recipients": len(users),
            "push_sent": fcm_success,
            "push_attempted": len(tokens),
            "notification_id": str(notification.id),
        }, status=status.HTTP_201_CREATED)


class NotificationListView(ListAPIView):
    """
    GET /api/v1/notifications/
    Admin: list all sent notifications.
    """
    serializer_class = NotificationSerializer
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        return Notification.objects.select_related(
            "sent_by", "target_program"
        ).all()


class MyNotificationsView(ListAPIView):
    """
    GET /api/v1/notifications/mine/
    Student: list their own notifications.
    """
    serializer_class = StudentNotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return StudentNotification.objects.select_related(
            "notification"
        ).filter(user=self.request.user)


class MarkNotificationReadView(APIView):
    """
    POST /api/v1/notifications/<uuid:pk>/read/
    Student marks a notification as read.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            sn = StudentNotification.objects.get(
                pk=pk, user=request.user
            )
        except StudentNotification.DoesNotExist:
            return Response({"detail": "Not found."}, status=404)

        if not sn.is_read:
            sn.is_read = True
            sn.read_at = timezone.now()
            sn.save(update_fields=["is_read", "read_at"])

        return Response({"detail": "Marked as read."})


class UnreadCountView(APIView):
    """
    GET /api/v1/notifications/unread-count/
    Returns the count of unread notifications for the current student.
    Used by the Flutter app to show the notification badge.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        count = StudentNotification.objects.filter(
            user=request.user, is_read=False
        ).count()
        return Response({"unread_count": count})
        
        
class LecturerSendNotificationView(APIView):
    """
    POST /api/v1/notifications/lecturer/send/
    Sends notification only to students enrolled in the specified unit this term.
    Body: { "title": "...", "message": "...", "notification_type": "...", "unit_id": "<uuid>" }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role != "lecturer":
            return Response({"detail": "Only lecturers can use this endpoint."}, status=403)

        title = request.data.get("title", "").strip()
        message = request.data.get("message", "").strip()
        notification_type = request.data.get("notification_type", "general")
        unit_id = request.data.get("unit_id", "").strip()

        if not title or not message:
            return Response({"detail": "Title and message are required."}, status=400)

        if not unit_id:
            return Response({"detail": "unit_id is required."}, status=400)

        # Get current term
        from apps.timetable.models import AcademicTerm
        term = AcademicTerm.objects.filter(is_current=True).first()
        if not term:
            return Response({"detail": "No current academic term set."}, status=400)

        # Get only students enrolled in this specific unit this term
        from apps.courses.models import StudentUnit
        student_ids = StudentUnit.objects.filter(
            unit_id=unit_id, term=term
        ).values_list("user_id", flat=True)

        users = list(User.objects.filter(id__in=student_ids, is_active=True))

        if not users:
            return Response({
                "detail": "No students enrolled in this unit for the current term.",
                "recipients": 0,
            }, status=200)

        notification = Notification.objects.create(
            sent_by=request.user,
            title=title,
            message=message,
            notification_type=notification_type,
            target=Notification.Target.ALL,
            recipients_count=len(users),
        )

        StudentNotification.objects.bulk_create([
            StudentNotification(user=user, notification=notification)
            for user in users
        ], ignore_conflicts=True)

        user_ids = [u.id for u in users]
        tokens = list(FCMToken.objects.filter(user_id__in=user_ids).values_list("token", flat=True))
        fcm_success = send_to_tokens(tokens, title, message, data={"type": notification_type}) if tokens else 0

        return Response({
            "detail": "Notification sent.",
            "recipients": len(users),
            "push_sent": fcm_success,
            "push_attempted": len(tokens),
        }, status=201)
