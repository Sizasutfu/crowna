from django.conf import settings
from django.db import models, transaction
from django.utils import timezone


class Contest(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"

    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    image = models.ImageField(
        upload_to="contests/",
        blank=True,
        null=True,
        help_text="Optional cover image.",
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-starts_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="contest_ends_after_starts",
            ),
        ]

    def __str__(self):
        return self.title

    def is_open_now(self):
        now = timezone.now()
        return (
            self.status == self.Status.OPEN
            and self.starts_at <= now < self.ends_at
        )

    def close(self):
        if self.status == self.Status.CLOSED:
            return False
        with transaction.atomic():
            locked = Contest.objects.select_for_update().get(pk=self.pk)
            if locked.status == self.Status.CLOSED:
                return False
            locked.status = self.Status.CLOSED
            locked.closed_at = timezone.now()
            locked.save(update_fields=["status", "closed_at"])
        self.refresh_from_db()
        return True

    def winners(self):
        top = self.contestants.order_by("-vote_count").first()
        if not top or top.vote_count == 0:
            return self.contestants.none()
        return self.contestants.filter(vote_count=top.vote_count).order_by("name")


class Contestant(models.Model):
    contest = models.ForeignKey(
        Contest,
        on_delete=models.CASCADE,
        related_name="contestants",
    )
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
    image = models.ImageField(
        upload_to="contestants/",
        blank=True,
        null=True,
        help_text="Optional profile image.",
    )
    bio = models.TextField(
        blank=True,
        default="",
        help_text="Short description shown on the profile page.",
    )
    vote_count = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-vote_count"]
        constraints = [
            models.UniqueConstraint(
                fields=["contest", "slug"],
                name="unique_contestant_slug_per_contest",
            ),
        ]

    def __str__(self):
        return f"{self.name} — {self.contest.title}"


class Vote(models.Model):
    contest = models.ForeignKey(
        Contest,
        on_delete=models.CASCADE,
        related_name="votes",
    )
    contestant = models.ForeignKey(
        Contestant,
        on_delete=models.CASCADE,
        related_name="votes",
    )
    voter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="votes",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["contest", "voter"],
                name="one_vote_per_user_per_contest",
            ),
        ]
        indexes = [
            models.Index(fields=["contestant"]),
        ]

    def __str__(self):
        return f"{self.voter} → {self.contestant} ({self.contest})"