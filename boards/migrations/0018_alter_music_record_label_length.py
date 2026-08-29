from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("boards", "0017_musicartist_applerecord_artist_spotifyrecord_artist_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="applerecord",
            name="label",
            field=models.CharField(max_length=128, verbose_name="指标"),
        ),
        migrations.AlterField(
            model_name="spotifyrecord",
            name="label",
            field=models.CharField(max_length=128, verbose_name="指标"),
        ),
    ]
