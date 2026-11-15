from django.contrib import admin
from django.utils.html import format_html

from .models import Contest, Contestant, Vote


def thumbnail(obj, size=48):
    if not obj.image:
        return "—"
    return format_html(
        '<img src="{}" style="height:{}px;width:{}px;object-fit:cover;border-radius:4px;" />',
        obj.image.url, size, size,
    )


class ContestantInline(admin.TabularInline):
    model = Contestant
    extra = 1
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("vote_count", "thumbnail_preview")
    fields = ("name", "slug", "image", "thumbnail_preview", "bio", "vote_count")

    @admin.display(description="Image")
    def thumbnail_preview(self, obj):
        return thumbnail(obj)


@admin.action(description="Close selected contests")
def close_contests(modeladmin, request, queryset):
    closed = 0
    for contest in queryset:
        if contest.close():
            closed += 1
    modeladmin.message_user(request, f"Closed {closed} contest(s).")


@admin.register(Contest)
class ContestAdmin(admin.ModelAdmin):
    list_display = (
        "thumbnail_preview", "title", "status",
        "starts_at", "ends_at", "closed_at", "winner_display",
    )
    list_filter = ("status",)
    prepopulated_fields = {"slug": ("title",)}
    inlines = [ContestantInline]
    actions = [close_contests]
    readonly_fields = ("closed_at", "thumbnail_preview")
    fields = (
        "title", "slug", "status", "image", "thumbnail_preview",
        "starts_at", "ends_at", "closed_at",
    )

    @admin.display(description="Image")
    def thumbnail_preview(self, obj):
        return thumbnail(obj)

    @admin.display(description="Winner(s)")
    def winner_display(self, obj):
        winners = obj.winners()
        if not winners.exists():
            return "—"
        return ", ".join(f"{w.name} ({w.vote_count})" for w in winners)


@admin.register(Contestant)
class ContestantAdmin(admin.ModelAdmin):
    list_display = ("thumbnail_preview", "name", "contest", "vote_count")
    list_filter = ("contest",)
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("vote_count", "thumbnail_preview")

    @admin.display(description="Image")
    def thumbnail_preview(self, obj):
        return thumbnail(obj)


@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display = ("contestant", "contest", "voter", "created_at")
    list_filter = ("contest",)
    readonly_fields = ("contest", "contestant", "voter", "created_at")