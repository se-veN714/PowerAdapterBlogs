from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def delete_legacy_comments(apps, schema_editor):
    """Remove comments that predate mandatory authenticated ownership.

    The project owner chose to re-import the small legacy dataset instead of
    inventing user ownership or weakening the non-null invariant.
    """
    Comment = apps.get_model('comment', 'Comment')
    Comment.objects.using(schema_editor.connection.alias).all().delete()


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('comment', '0002_remove_comment_image_alter_comment_nickname_and_more'),
    ]

    operations = [
        migrations.RunPython(
            delete_legacy_comments,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AddField(
            model_name='comment',
            name='user',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='comments',
                to=settings.AUTH_USER_MODEL,
                verbose_name='评论者',
            ),
        ),
    ]
