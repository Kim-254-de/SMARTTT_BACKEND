"""
day_of_week is stored as a short string ('mon', 'tue', ...), so ordering
by it directly sorts alphabetically (fri, mon, sat, thu, tue, wed) rather
than calendar order. day_of_week_sort_case() gives an annotation that
sorts it correctly - use it wherever timetable slots/sessions need to be
listed or displayed in real week order (Monday through Saturday).
"""
from django.db.models import Case, IntegerField, Value, When

DAY_OF_WEEK_ORDER = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def day_of_week_sort_case(field_name="day_of_week"):
    """
    Returns a Case expression mapping day_of_week values to their real
    calendar position (Monday=0 ... Sunday=6), for use in .annotate() +
    .order_by(), e.g.:

        queryset.annotate(_day_sort=day_of_week_sort_case()) \\
                .order_by("_day_sort", "start_time")

    field_name lets this be reused for a related field too, e.g.
    day_of_week_sort_case("time_slot__day_of_week").
    """
    return Case(
        *[When(**{field_name: day}, then=Value(i)) for day, i in DAY_OF_WEEK_ORDER.items()],
        default=Value(99),
        output_field=IntegerField(),
    )
