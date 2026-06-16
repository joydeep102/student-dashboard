import logging

from django.db import transaction
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .google_meet import can_create_meet, delete_meet_event, ensure_meet_link
from .models import LiveClass

log = logging.getLogger(__name__)


@receiver(post_save, sender=LiveClass)
def auto_create_meet_link(sender, instance: LiveClass, created, **kwargs):
    """Generate a Meet link the first time a class is saved without one.

    Deferred to on_commit so the class's allowed_plans (saved after the row,
    e.g. by the admin form or the trainer view) are present when we build the
    Calendar invite list. No-ops when Google isn't connected.
    """
    if instance.meet_link:
        return
    pk = instance.pk

    def _run():
        lc = (
            LiveClass.objects.select_related("batch__course")
            .filter(pk=pk)
            .first()
        )
        if lc:
            ensure_meet_link(lc)

    transaction.on_commit(_run)


@receiver(post_delete, sender=LiveClass)
def cleanup_meet_event(sender, instance: LiveClass, **kwargs):
    if instance.google_event_id and can_create_meet(instance):
        delete_meet_event(instance.google_event_id, instance)
