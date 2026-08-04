from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0010_myuser_privileged_session_version"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="myuser",
            name="is_reviewer",
        ),
    ]
