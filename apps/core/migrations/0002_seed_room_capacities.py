from django.db import migrations

ROOM_CAPACITIES = [
    ("MLS Hall 2", 90), ("MLS Hall 1", 70),
    ("TC 1", 110), ("TC 4", 110), ("TC 5", 100), ("TC 6", 100),
    ("TC 7", 110), ("TC 8", 100), ("TC 9", 100), ("TC 10", 100), ("TC 11", 100),
    ("ED 3", 110),
    ("ED 7", 120), ("ED 6", 120), ("ED 5", 120), ("ED 4", 110),
    ("STB 1", 800), ("STB 2", 140), ("STB 3", 110), ("STB 4", 110),
    ("STB 5", 110), ("STB 6", 110), ("STB 7", 210), ("STB 8", 210),
    ("UTC 1", 1000), ("UTC 2", 300), ("UTC 3", 450), ("UTC 4", 450),
    ("UTC 5", 450), ("UTC 6", 252), ("UTC 7", 210), ("UTC 8", 210),
    ("UTC 9", 210), ("UTC 11", 130), ("UTC 12", 72),
    ("UTC 13", 280), ("UTC 14", 280),
]

# GZ block: GZ 1 through GZ 80, capacity 12 each
ROOM_CAPACITIES += [(f"GZ {i}", 12) for i in range(1, 81)]


def seed_rooms(apps, schema_editor):
    Room = apps.get_model("rooms", "Room")
    for code, capacity in ROOM_CAPACITIES:
        Room.objects.update_or_create(
            code=code,
            defaults={"capacity": capacity, "name": code, "building": code.split()[0]},
        )

def reverse(apps, schema_editor):
    pass

class Migration(migrations.Migration):
    dependencies = [("rooms", "0001_initial")]
    operations = [migrations.RunPython(seed_rooms, reverse)]