"""Invalidate pending requests on loss of account/capability, including restore races."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models import Q, F
from django.db.models.signals import post_save, m2m_changed, pre_delete
from django.dispatch import receiver

from padif.models import Document, DocumentAgentRequest
from padif.permissions import can_use_padif
from .access import lock_identity, invalidate_pending
from .models import AgentQualification, AgentAccessRequest


@transaction.atomic
def invalidate_user_requests(user_id):
    user = lock_identity(user_id)
    if can_use_padif(user):
        return
    list(AgentQualification.objects.select_for_update().filter(user=user, module_key='padif'))
    AgentQualification.objects.filter(user=user, module_key='padif').update(revision=F('revision') + 1)
    invalidate_pending(AgentAccessRequest.objects.filter(applicant=user, module_key='padif'), 'padif_access_lost')
    invalidate_pending(DocumentAgentRequest.objects.filter(applicant=user, module_key='padif'), 'padif_access_lost')


@receiver(post_save, sender=get_user_model())
def account_changed(sender, instance, created=False, raw=False, **kwargs):
    if not created and not raw:
        invalidate_user_requests(instance.pk)


@receiver(m2m_changed, sender=get_user_model().user_permissions.through)
@receiver(m2m_changed, sender=get_user_model().groups.through)
@receiver(m2m_changed, sender=Group.permissions.through)
def capabilities_changed(sender, instance, action, **kwargs):
    if action not in {'post_add', 'post_remove', 'post_clear'}:
        return
    if isinstance(instance, get_user_model()):
        ids = [instance.pk]
    else:
        ids = list(get_user_model().objects.filter(Q(agent_access_requests__status='pending') |
            Q(document_agent_requests__status='pending') | Q(agent_qualifications__is_active=True)).values_list('pk', flat=True).distinct())
    for user_id in sorted(ids):
        invalidate_user_requests(user_id)


@receiver(pre_delete, sender=Document)
def document_deleted(sender, instance, **kwargs):
    Document.objects.select_for_update().get(pk=instance.pk)
    invalidate_pending(DocumentAgentRequest.objects.filter(document=instance), 'document_deleted')
