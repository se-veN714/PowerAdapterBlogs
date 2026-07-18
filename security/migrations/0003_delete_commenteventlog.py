from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('security', '0002_commenteventlog'),
    ]

    operations = [
        migrations.DeleteModel(
            name='CommentEventLog',
        ),
    ]
