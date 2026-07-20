from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .services import generate_for_user
from datetime import datetime, timedelta

import pytz
from django.http import HttpResponse
from icalendar import Alarm, Calendar, Event

from apps.courses.models import StudentUnit
from apps.timetable.models import AcademicTerm, TimetableSlot

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
class MyCalendarFeedView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
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
