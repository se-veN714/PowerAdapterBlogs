from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('boards', '0005_board_index_content'),
    ]

    operations = [
        migrations.AddField(
            model_name='appleentry',
            name='value2',
            field=models.CharField(blank=True, max_length=64, verbose_name='次值'),
        ),
        migrations.AddField(
            model_name='appleentry',
            name='note',
            field=models.TextField(blank=True, verbose_name='注记'),
        ),
        migrations.AddField(
            model_name='spotifyentry',
            name='value2',
            field=models.CharField(blank=True, max_length=64, verbose_name='次值'),
        ),
        migrations.AddField(
            model_name='spotifyentry',
            name='note',
            field=models.TextField(blank=True, verbose_name='注记'),
        ),
    ]
