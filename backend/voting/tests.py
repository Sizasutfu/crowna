from datetime import timedelta
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from .models import Contest, Contestant, Vote

User = get_user_model()

FAST_HASHER = "django.contrib.auth.hashers.MD5PasswordHasher"


# ---------------------------------------------------------------------------
# Voting endpoint
# ---------------------------------------------------------------------------

@override_settings(PASSWORD_HASHERS=[FAST_HASHER])
class VoteEndpointTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.voter = User.objects.create_user("voter_a", password="pass12345")
        self.voter_b = User.objects.create_user("voter_b", password="pass12345")

        self.contest = Contest.objects.create(
            title="Test Contest",
            slug="test-contest",
            status=Contest.Status.OPEN,
            starts_at=self.now - timedelta(hours=1),
            ends_at=self.now + timedelta(hours=1),
        )
        self.contestant = Contestant.objects.create(
            contest=self.contest, name="Artist A", slug="artist-a",
        )

    def vote_url(self, contest=None, contestant=None):
        return reverse(
            "voting:cast_vote",
            args=[
                (contest or self.contest).id,
                (contestant or self.contestant).id,
            ],
        )

    # --- happy path -------------------------------------------------

    def test_vote_is_accepted_and_increments_exactly_once(self):
        self.client.force_login(self.voter)
        r = self.client.post(self.vote_url())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["vote_count"], 1)
        self.contestant.refresh_from_db()
        self.assertEqual(self.contestant.vote_count, 1)
        self.assertEqual(Vote.objects.count(), 1)

    # --- duplicate / one-vote-per-user ------------------------------

    def test_duplicate_vote_returns_409_and_does_not_increment(self):
        self.client.force_login(self.voter)
        self.client.post(self.vote_url())
        r2 = self.client.post(self.vote_url())
        self.assertEqual(r2.status_code, 409)
        self.contestant.refresh_from_db()
        self.assertEqual(self.contestant.vote_count, 1)
        self.assertEqual(Vote.objects.count(), 1)

    def test_two_different_users_each_get_one_vote(self):
        self.client.force_login(self.voter)
        self.assertEqual(self.client.post(self.vote_url()).status_code, 200)
        self.client.force_login(self.voter_b)
        self.assertEqual(self.client.post(self.vote_url()).status_code, 200)
        self.contestant.refresh_from_db()
        self.assertEqual(self.contestant.vote_count, 2)
        self.assertEqual(Vote.objects.count(), 2)

    def test_same_user_may_vote_in_a_different_contest(self):
        other = Contest.objects.create(
            title="Other", slug="other", status=Contest.Status.OPEN,
            starts_at=self.now - timedelta(hours=1),
            ends_at=self.now + timedelta(hours=1),
        )
        other_contestant = Contestant.objects.create(
            contest=other, name="B", slug="b",
        )
        self.client.force_login(self.voter)
        self.assertEqual(self.client.post(self.vote_url()).status_code, 200)
        self.assertEqual(
            self.client.post(self.vote_url(other, other_contestant)).status_code,
            200,
        )
        self.assertEqual(Vote.objects.filter(voter=self.voter).count(), 2)

    # --- auth / method guards --------------------------------------

    def test_anonymous_vote_redirects_to_login(self):
        r = self.client.post(self.vote_url())
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login/", r["Location"].lower())
        self.assertEqual(Vote.objects.count(), 0)

    def test_get_request_is_rejected(self):
        self.client.force_login(self.voter)
        r = self.client.get(self.vote_url())
        self.assertEqual(r.status_code, 405)
        self.assertEqual(Vote.objects.count(), 0)

    # --- voting window / status ------------------------------------

    def test_vote_blocked_before_start(self):
        self.contest.starts_at = self.now + timedelta(hours=1)
        self.contest.ends_at = self.now + timedelta(hours=2)
        self.contest.save()
        self.client.force_login(self.voter)
        self.assertEqual(self.client.post(self.vote_url()).status_code, 403)

    def test_vote_blocked_after_end(self):
        self.contest.starts_at = self.now - timedelta(hours=2)
        self.contest.ends_at = self.now - timedelta(hours=1)
        self.contest.save()
        self.client.force_login(self.voter)
        self.assertEqual(self.client.post(self.vote_url()).status_code, 403)

    def test_vote_blocked_when_status_not_open(self):
        self.contest.status = Contest.Status.DRAFT
        self.contest.save()
        self.client.force_login(self.voter)
        self.assertEqual(self.client.post(self.vote_url()).status_code, 403)

    # --- cross-contest integrity -----------------------------------

    def test_vote_for_contestant_from_another_contest_is_404(self):
        other = Contest.objects.create(
            title="Other", slug="other", status=Contest.Status.OPEN,
            starts_at=self.now - timedelta(hours=1),
            ends_at=self.now + timedelta(hours=1),
        )
        foreign_contestant = Contestant.objects.create(
            contest=other, name="B", slug="b",
        )
        self.client.force_login(self.voter)
        r = self.client.post(self.vote_url(self.contest, foreign_contestant))
        self.assertEqual(r.status_code, 404)
        self.assertEqual(Vote.objects.count(), 0)

    def test_vote_for_nonexistent_contestant_is_404(self):
        self.client.force_login(self.voter)
        r = self.client.post(
            reverse("voting:cast_vote", args=[self.contest.id, 999999])
        )
        self.assertEqual(r.status_code, 404)


# ---------------------------------------------------------------------------
# Contest lifecycle
# ---------------------------------------------------------------------------

@override_settings(PASSWORD_HASHERS=[FAST_HASHER])
class ContestLifecycleTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.contest = Contest.objects.create(
            title="Lifecycle",
            slug="lifecycle",
            status=Contest.Status.OPEN,
            starts_at=self.now - timedelta(hours=1),
            ends_at=self.now + timedelta(hours=1),
        )
        self.voter = User.objects.create_user("lifecycle_voter", password="pass12345")

    def test_close_sets_status_and_timestamp(self):
        self.assertTrue(self.contest.close())
        self.contest.refresh_from_db()
        self.assertEqual(self.contest.status, Contest.Status.CLOSED)
        self.assertIsNotNone(self.contest.closed_at)

    def test_close_is_idempotent(self):
        self.assertTrue(self.contest.close())
        self.assertFalse(self.contest.close())

    def test_closing_contest_blocks_further_votes(self):
        self.contestant = Contestant.objects.create(
            contest=self.contest, name="A", slug="a",
        )
        url = reverse("voting:cast_vote", args=[self.contest.id, self.contestant.id])

        self.client.force_login(self.voter)
        self.assertEqual(self.client.post(url).status_code, 200)

        self.contest.close()
        self.contest.refresh_from_db()

        other_voter = User.objects.create_user("other_voter", password="pass12345")
        self.client.force_login(other_voter)
        self.assertEqual(self.client.post(url).status_code, 403)

        self.contestant.refresh_from_db()
        self.assertEqual(self.contestant.vote_count, 1)
        self.assertEqual(Vote.objects.count(), 1)

    def test_winners_includes_ties(self):
        a = Contestant.objects.create(contest=self.contest, name="Artist A", slug="a")
        b = Contestant.objects.create(contest=self.contest, name="Artist B", slug="b")
        Contestant.objects.filter(pk__in=[a.pk, b.pk]).update(vote_count=5)

        winners = list(self.contest.winners())
        self.assertEqual(len(winners), 2)
        self.assertEqual({w.name for w in winners}, {"Artist A", "Artist B"})

    def test_winners_empty_when_no_votes(self):
        Contestant.objects.create(contest=self.contest, name="Solo", slug="solo")
        self.assertEqual(self.contest.winners().count(), 0)


# ---------------------------------------------------------------------------
# Signup
# ---------------------------------------------------------------------------

@override_settings(PASSWORD_HASHERS=[FAST_HASHER])
class SignupTests(TestCase):
    def test_signup_creates_user_and_logs_them_in(self):
        r = self.client.post("/signup/", {
            "username": "newuser",
            "email": "new@example.com",
            "password1": "securepass123",
            "password2": "securepass123",
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/")
        self.assertTrue(User.objects.filter(username="newuser").exists())
        self.assertEqual(
            int(self.client.session["_auth_user_id"]),
            User.objects.get(username="newuser").id,
        )

    def test_signup_rejects_duplicate_email_case_insensitively(self):
        User.objects.create_user(
            "existing", email="dup@example.com", password="pass12345"
        )
        r = self.client.post("/signup/", {
            "username": "newuser",
            "email": "DUP@Example.com",
            "password1": "securepass123",
            "password2": "securepass123",
        })
        self.assertEqual(r.status_code, 200)   # form re-rendered with errors
        self.assertFalse(User.objects.filter(username="newuser").exists())

    def test_signup_rejects_mismatched_passwords(self):
        r = self.client.post("/signup/", {
            "username": "newuser",
            "email": "new@example.com",
            "password1": "securepass123",
            "password2": "different456",
        })
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(username="newuser").exists())

    def test_logged_in_user_redirected_away_from_signup(self):
        User.objects.create_user("existing", password="pass12345")
        self.client.force_login(User.objects.get(username="existing"))
        r = self.client.get("/signup/")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/")


# ---------------------------------------------------------------------------
# Contestant profile
# ---------------------------------------------------------------------------

@override_settings(PASSWORD_HASHERS=[FAST_HASHER])
class ContestantProfileTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.contest = Contest.objects.create(
            title="Profile Contest",
            slug="profile-contest",
            status=Contest.Status.OPEN,
            starts_at=self.now - timedelta(hours=1),
            ends_at=self.now + timedelta(hours=1),
        )
        self.leader = Contestant.objects.create(
            contest=self.contest, name="Leader", slug="leader",
            bio="Top of the pack.", vote_count=10,
        )
        self.runner = Contestant.objects.create(
            contest=self.contest, name="Runner", slug="runner", vote_count=5,
        )
        self.other = Contestant.objects.create(
            contest=self.contest, name="Other", slug="other", vote_count=2,
        )
        self.voter = User.objects.create_user("profile_voter", password="pass12345")

    def profile_url(self, contestant=None):
        return reverse("voting:contestant_detail", args=[(contestant or self.leader).id])

    def test_profile_renders_with_correct_rank(self):
        r = self.client.get(self.profile_url(self.leader))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Leader")
        self.assertEqual(r.context["rank"], 1)

        r = self.client.get(self.profile_url(self.runner))
        self.assertEqual(r.context["rank"], 2)

        r = self.client.get(self.profile_url(self.other))
        self.assertEqual(r.context["rank"], 3)

    def test_profile_shows_bio(self):
        r = self.client.get(self.profile_url(self.leader))
        self.assertContains(r, "Top of the pack.")

    def test_profile_computes_vote_share(self):
        # 10 + 5 + 2 = 17 total; leader share = 10/17 = 58.8%
        r = self.client.get(self.profile_url(self.leader))
        self.assertEqual(r.context["total_votes"], 17)
        self.assertEqual(r.context["share"], 58.8)

    def test_nonexistent_contestant_is_404(self):
        r = self.client.get(reverse("voting:contestant_detail", args=[999999]))
        self.assertEqual(r.status_code, 404)

    def test_vote_from_profile_redirects_back_to_profile(self):
        url = reverse("voting:cast_vote", args=[self.contest.id, self.runner.id])
        self.client.force_login(self.voter)
        r = self.client.post(
            url,
            {"next": self.profile_url(self.runner)},
            HTTP_ACCEPT="text/html",
        )
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], self.profile_url(self.runner))

    def test_vote_ignores_offsite_next(self):
        url = reverse("voting:cast_vote", args=[self.contest.id, self.runner.id])
        self.client.force_login(self.voter)
        r = self.client.post(
            url,
            {"next": "https://evil.example.com/phish"},
            HTTP_ACCEPT="text/html",
        )
        self.assertEqual(r.status_code, 302)
        self.assertIn(f"/contests/{self.contest.id}/", r["Location"])
        self.assertNotIn("evil", r["Location"])


# ---------------------------------------------------------------------------
# Landing page
# ---------------------------------------------------------------------------

@override_settings(PASSWORD_HASHERS=[FAST_HASHER])
class LandingPageTests(TestCase):
    def test_home_renders(self):
        r = self.client.get(reverse("voting:home"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Crown the")

    def test_contest_list_lives_at_contests_path(self):
        r = self.client.get("/contests/")
        self.assertEqual(r.status_code, 200)

    def test_home_shows_open_contests(self):
        now = timezone.now()
        Contest.objects.create(
            title="Live Contest",
            slug="live-contest",
            status=Contest.Status.OPEN,
            starts_at=now - timedelta(hours=1),
            ends_at=now + timedelta(hours=1),
        )
        r = self.client.get(reverse("voting:home"))
        self.assertContains(r, "Live Contest")

    def test_home_hides_closed_contests_from_featured_section(self):
        now = timezone.now()
        Contest.objects.create(
            title="Closed Contest",
            slug="closed-contest",
            status=Contest.Status.CLOSED,
            starts_at=now - timedelta(days=2),
            ends_at=now - timedelta(days=1),
            closed_at=now - timedelta(days=1),
        )
        r = self.client.get(reverse("voting:home"))
        self.assertNotContains(r, "Closed Contest")

    def test_signup_redirects_to_home(self):
        r = self.client.post("/signup/", {
            "username": "newuser",
            "email": "new@example.com",
            "password1": "securepass123",
            "password2": "securepass123",
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], reverse("voting:home"))


# ---------------------------------------------------------------------------
# Results page
# ---------------------------------------------------------------------------

@override_settings(PASSWORD_HASHERS=[FAST_HASHER])
class ResultsPageTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.contest = Contest.objects.create(
            title="Results Contest",
            slug="results-contest",
            status=Contest.Status.CLOSED,
            starts_at=self.now - timedelta(days=2),
            ends_at=self.now - timedelta(days=1),
            closed_at=self.now - timedelta(days=1),
        )
        self.winner = Contestant.objects.create(
            contest=self.contest, name="Winner", slug="winner", vote_count=100,
        )
        self.second = Contestant.objects.create(
            contest=self.contest, name="Second", slug="second", vote_count=50,
        )
        self.third = Contestant.objects.create(
            contest=self.contest, name="Third", slug="third", vote_count=25,
        )

    def results_url(self):
        return reverse("voting:contest_results", args=[self.contest.id])

    def test_results_renders_for_closed_contest(self):
        r = self.client.get(self.results_url())
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Results Contest")
        self.assertContains(r, "Winner")

    def test_results_redirects_when_contest_open(self):
        self.contest.status = Contest.Status.OPEN
        self.contest.closed_at = None
        self.contest.save()
        r = self.client.get(self.results_url())
        self.assertEqual(r.status_code, 302)
        self.assertIn(f"/contests/{self.contest.id}/", r["Location"])

    def test_results_identifies_correct_winner(self):
        r = self.client.get(self.results_url())
        self.assertEqual(len(r.context["winners"]), 1)
        self.assertEqual(r.context["winners"][0].name, "Winner")

    def test_results_aggregates_total_votes(self):
        r = self.client.get(self.results_url())
        self.assertEqual(r.context["total_votes"], 175)

    def test_results_handles_ties(self):
        Contestant.objects.filter(pk=self.second.pk).update(vote_count=100)
        r = self.client.get(self.results_url())
        winner_names = {w.name for w in r.context["winners"]}
        self.assertEqual(winner_names, {"Winner", "Second"})

    def test_results_with_no_votes(self):
        Contestant.objects.filter(contest=self.contest).update(vote_count=0)
        r = self.client.get(self.results_url())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context["winners"]), 0)
        self.assertContains(r, "No votes were cast")

    def test_results_has_open_graph_tags(self):
        r = self.client.get(self.results_url())
        self.assertContains(r, 'property="og:title"')
        self.assertContains(r, 'property="og:url"')
        self.assertContains(r, 'name="twitter:card"')

    def test_nonexistent_contest_is_404(self):
        r = self.client.get(reverse("voting:contest_results", args=[999999]))
        self.assertEqual(r.status_code, 404)

    def test_closed_contest_detail_shows_results_link(self):
        r = self.client.get(reverse("voting:contest_detail", args=[self.contest.id]))
        self.assertContains(r, "View final results")


# ---------------------------------------------------------------------------
# Image conversion (WebP)
# ---------------------------------------------------------------------------

@override_settings(PASSWORD_HASHERS=[FAST_HASHER])
class ImageConversionTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.contest = Contest.objects.create(
            title="Image Contest",
            slug="image-contest",
            status=Contest.Status.OPEN,
            starts_at=self.now - timedelta(hours=1),
            ends_at=self.now + timedelta(hours=1),
        )

    def _jpg_upload(self, name="test.jpg", size=(100, 100), color="red"):
        img = Image.new("RGB", size, color=color)
        buf = BytesIO()
        img.save(buf, format="JPEG")
        buf.seek(0)
        return SimpleUploadedFile(name, buf.read(), content_type="image/jpeg")

    def _webp_upload(self, name="already.webp", size=(100, 100), color="blue"):
        img = Image.new("RGB", size, color=color)
        buf = BytesIO()
        img.save(buf, format="WEBP")
        buf.seek(0)
        return SimpleUploadedFile(name, buf.read(), content_type="image/webp")

    def _is_webp(self, field_file):
        field_file.open("rb")
        header = field_file.read(12)
        field_file.close()
        return header[:4] == b"RIFF" and header[8:12] == b"WEBP"

    def test_contestant_jpg_is_converted_to_webp(self):
        contestant = Contestant.objects.create(
            contest=self.contest,
            name="Jpg Art",
            slug="jpg-art",
            image=self._jpg_upload(),
        )
        contestant.refresh_from_db()
        self.assertTrue(contestant.image.name.lower().endswith(".webp"))
        self.assertTrue(self._is_webp(contestant.image))

    def test_contest_jpg_is_converted_to_webp(self):
        contest = Contest.objects.create(
            title="Cover Contest",
            slug="cover-contest",
            status=Contest.Status.OPEN,
            starts_at=self.now - timedelta(hours=1),
            ends_at=self.now + timedelta(hours=1),
            image=self._jpg_upload("cover.jpg"),
        )
        contest.refresh_from_db()
        self.assertTrue(contest.image.name.lower().endswith(".webp"))
        self.assertTrue(self._is_webp(contest.image))

    def test_existing_webp_upload_is_not_reconverted(self):
        contestant = Contestant.objects.create(
            contest=self.contest,
            name="WebP Native",
            slug="webp-native",
            image=self._webp_upload(),
        )
        contestant.refresh_from_db()
        self.assertTrue(contestant.image.name.lower().endswith(".webp"))
        self.assertIn("already", contestant.image.name)

    def test_oversized_image_is_downscaled(self):
        contestant = Contestant.objects.create(
            contest=self.contest,
            name="Big Art",
            slug="big-art",
            image=self._jpg_upload("big.jpg", size=(3000, 2000), color="green"),
        )
        contestant.refresh_from_db()

        contestant.image.open("rb")
        saved = Image.open(contestant.image)
        contestant.image.close()

        # Contestant max_dim is 800 in signals.py
        self.assertLessEqual(max(saved.size), 800)