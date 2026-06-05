from django.db import migrations


def add_leave_types(apps, schema_editor):
    """Ensure 'Sick leave' and 'Other' leave types exist (idempotent)."""
    LeaveType = apps.get_model('leaves', 'LeaveType')
    seed = [
        {'name': 'Sick leave', 'max_days_per_year': 10, 'is_paid': True,
         'description': 'Leave taken due to illness or medical reasons.', 'color': '#e63946'},
        {'name': 'Other', 'max_days_per_year': 5, 'is_paid': False,
         'description': 'Any other leave not covered by the standard types.', 'color': '#6c757d'},
    ]
    for item in seed:
        # Case-insensitive guard so we don't create a duplicate of an
        # existing type that differs only by capitalisation (e.g. "Sick Leave").
        if not LeaveType.objects.filter(name__iexact=item['name']).exists():
            LeaveType.objects.create(**item)


def remove_leave_types(apps, schema_editor):
    LeaveType = apps.get_model('leaves', 'LeaveType')
    LeaveType.objects.filter(name__in=['Sick leave', 'Other']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('leaves', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(add_leave_types, remove_leave_types),
    ]
