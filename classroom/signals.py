import logging

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .google_meet import GoogleMeetUnavailable, create_meet_event, delete_meet_event, is_configured
from .models import LiveClass

log = logging.getLogger(__name__)


@receiver(post_save, sender=LiveClass)
def auto_create_meet_link(sender, instance: LiveClass, created, **kwargs):
    """Generate a Meet link the first time a class is saved without one.

    Silently no-ops (leaving the admin free to paste a link) when Google
    credentials aren't configured, so the portal works out of the box.
    """
    if instance.meet_link or not is_configured():
        return
    try:
        meet_link, event_id = create_meet_event(instance)
    except GoogleMeetUnavailable as exc:
        log.warning("Meet link not created for LiveClass %s: %s", instance.pk, exc)
        return
    except Exception:  # network/API errors shouldn't crash the save
        log.exception("Unexpected error creating Meet link for LiveClass %s", instance.pk)
        return

    if meet_link:
        # Update without re-triggering this signal.
        LiveClass.objects.filter(pk=instance.pk).update(
            meet_link=meet_link, google_event_id=event_id
        )


@receiver(post_delete, sender=LiveClass)
def cleanup_meet_event(sender, instance: LiveClass, **kwargs):
    if instance.google_event_id and is_configured():
        delete_meet_event(instance.google_event_id)
