from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .services import generate_for_user
from datetime import datetime, timedelta

import pytz
from django.contrib.auth import get_user_model
from django.core import signing
from django.http import HttpResponse
from django.urls import reverse
from icalendar import Alarm, Calendar, Event

from apps.courses.models import StudentUnit
from apps.timetable.models import AcademicTerm, TimetableSlot

# Salt for signing calendar feed tokens (not a secret on its own —
# the actual signing key is Django's SECRET_KEY)
CALENDAR_TOKEN_SALT = "smarttt-calendar-feed"

# 5 years — effectively "doesn't expire" for a subscribed feed
CALENDAR_TOKEN_MAX_AGE = 60 * 60 * 24 * 365 * 5

class MyScheduleView(APIView):
    """
    GET /api/v1/schedule/me/
    Returns the personalised timetable for the authenticated student.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        payload = generate_for_user(request.user)
        return Response(payload)

#iCalendar feed view for the authenticated user
class CalendarTokenView(APIView):
    """
    GET /api/v1/schedule/calendar-token/
    Returns a long-lived signed token the authenticated user embeds in
    their calendar.ics subscription URL. Calendar apps (Google/Apple/
    Outlook) poll .ics URLs without sending Authorization headers, so
    the feed itself can't require normal JWT auth.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        token = signing.dumps(
            {'user_id': request.user.id}, salt=CALENDAR_TOKEN_SALT
        )
        feed_path = reverse('my-calendar-feed')
        feed_url = request.build_absolute_uri(f'{feed_path}?token={token}')
        return Response({'token': token, 'feed_url': feed_url})


#iCalendar feed view — token-authenticated for calendar-app subscriptions
class MyCalendarFeedView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []  # token is in the query string, not a header

    def get(self, request):
        token = request.query_params.get('token')
        if not token:
            return HttpResponse('Missing token', status=401)

        try:
            data = signing.loads(
                token,
                salt=CALENDAR_TOKEN_SALT,
                max_age=CALENDAR_TOKEN_MAX_AGE,
            )
        except signing.BadSignature:
            return HttpResponse('Invalid or expired token', status=401)

        User = get_user_model()
        try:
            user = User.objects.get(pk=data['user_id'])
        except User.DoesNotExist:
            return HttpResponse('Invalid token', status=401)

        tz = pytz.timezone('Africa/Nairobi')

        term = AcademicTerm.objects.filter(is_current=True).first()
        if not term:
            return HttpResponse('No current term', status=404)

        cal = Calendar()
        cal.add('prodid', '-//Smart TT//Tharaka University//EN')
        cal.add('version', '2.0')
        cal.add('x-wr-calname', f'Smart TT - {user.get_full_name()}')
        cal.add('x-wr-timezone', 'Africa/Nairobi')

        # Student timetable
        if user.role == 'student':
            unit_ids = (
                StudentUnit.objects.filter(user=user, term=term)
                .values_list('unit_id', flat=True)
            )

            slots = TimetableSlot.objects.select_related(
                'unit', 'room', 'lecturer__user'
            ).filter(term=term, unit_id__in=unit_ids)

        # Lecturer timetable
        else:
            slots = TimetableSlot.objects.select_related(
                'unit', 'room', 'lecturer__user'
            ).filter(term=term, lecturer__user=user)

        day_map = {
            'MON': 'MO',
            'TUE': 'TU',
            'WED': 'WE',
            'THU': 'TH',
            'FRI': 'FR',
            'SAT': 'SA',
        }

        for slot in slots:
            event = Event()

            # First occurrence of the class in the semester
            current = term.start_date
            while current.weekday() != list(day_map.keys()).index(slot.day):
                current += timedelta(days=1)

            start_dt = tz.localize(
                datetime.combine(current, slot.start_time)
            )

            end_dt = tz.localize(
                datetime.combine(current, slot.end_time)
            )

            # Event title
            event.add(
                'summary',
                f'{slot.unit.code} - {slot.unit.name}'
            )

            # Venue
            if slot.room:
                event.add('location', slot.room.code)

            # Time
            event.add('dtstart', start_dt)
            event.add('dtend', end_dt)

            # Repeat every week until semester ends
            event.add('rrule', {
                'freq': 'weekly',
                'until': tz.localize(
                    datetime.combine(term.end_date, datetime.max.time())
                ),
                'byday': day_map[slot.day],
            })

            # Reminder 1: 30 minutes before
            alarm_30 = Alarm()
            alarm_30.add('action', 'DISPLAY')
            alarm_30.add(
                'description',
                f'{slot.unit.code} starts in 30 minutes'
            )
            alarm_30.add('trigger', timedelta(minutes=-30))
            event.add_component(alarm_30)

            # Reminder 2: 10 minutes before
            alarm_10 = Alarm()
            alarm_10.add('action', 'DISPLAY')
            alarm_10.add(
                'description',
                f'{slot.unit.code} starts in 10 minutes'
            )
            alarm_10.add('trigger', timedelta(minutes=-10))
            event.add_component(alarm_10)

            cal.add_component(event)

        response = HttpResponse(
            cal.to_ical(),
            content_type='text/calendar'
        )

        response['Content-Disposition'] = (
            'inline; filename="smarttt.ics"'
        )

        return response
