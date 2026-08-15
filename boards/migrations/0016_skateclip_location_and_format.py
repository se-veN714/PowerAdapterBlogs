from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("boards", "0015_skateclipmedia_claim_generation_and_more")]

    operations = [
        migrations.AlterField(
            model_name="skateclip",
            name="category",
            field=models.CharField(
                blank=True,
                choices=[("rotation", "Rotation"), ("displacement", "Displacement"), ("height", "Height")],
                max_length=32,
                verbose_name="动作类型",
            ),
        ),
        migrations.AddField(
            model_name="skateclip",
            name="clip_format",
            field=models.CharField(
                choices=[("clip", "Clip"), ("line", "Line"), ("b_roll", "B-roll")],
                default="clip",
                help_text="Clip=单个动作，Line=连续动作，B-roll=环境或过渡镜头",
                max_length=16,
                verbose_name="内容类型",
            ),
        ),
        migrations.AddField(
            model_name="skateclip",
            name="spot_address",
            field=models.CharField(blank=True, max_length=255, verbose_name="详细地址"),
        ),
        migrations.AddField(
            model_name="skateclip",
            name="spot_latitude",
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=8, null=True, verbose_name="纬度"),
        ),
        migrations.AddField(
            model_name="skateclip",
            name="spot_longitude",
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True, verbose_name="经度"),
        ),
    ]
