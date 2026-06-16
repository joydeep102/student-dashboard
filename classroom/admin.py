from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import LiveClass


@admin.register(LiveClass)
class LiveClassAdmin(admin.ModelAdmin):
    list_display = (
        "title", "batch", "start_time", "duration_minutes", "required_plan", "status", "meet_status",
    )
    list_filter = ("status", "batch", "required_plan", "start_time")
    search_fields = ("title", "description", "batch__name")
    autocomplete_fields = ["batch", "required_plan"]
    date_hierarchy = "start_time"
    readonly_fields = ("google_event_id", "meet_link_preview")
    fieldsets = (
        (None, {"fields": ("batch", "title", "description")}),
        (
            "Access",
            {
                "fields": ("required_plan",),
                "description": "Minimum plan to join. Blank = everyone in the batch can join. "
                "Set it to a higher plan so lower-plan students no longer get this class.",
            },
        ),
        ("Schedule", {"fields": ("start_time", "duration_minutes", "status")}),
        (
            "Google Meet",
            {
                "fields": ("meet_link", "meet_link_preview", "google_event_id"),
                "description": "Leave the link blank to auto-generate a Google Meet link on save "
                "(requires Google authorization). You can also paste one manually.",
            },
        ),
    )

    @admin.display(description="Meet")
    def meet_status(self, obj):
        if obj.meet_link:
            return mark_safe('<span style="color:#16a34a;">✓ link ready</span>')
        return mark_safe('<span style="color:#dc2626;">no link</span>')

    @admin.display(description="Open Meet")
    def meet_link_preview(self, obj):
        if obj.meet_link:
            return format_html('<a href="{}" target="_blank">{}</a>', obj.meet_link, obj.meet_link)
        return "— (will be generated on save if Google is configured)"
