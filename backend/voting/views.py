from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import F, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.views.generic.edit import CreateView

from .forms import SignupForm
from .models import Contest, Contestant, Vote


def home(request):
    now = timezone.now()
    open_contests = Contest.objects.filter(
        status=Contest.Status.OPEN,
        starts_at__lte=now,
        ends_at__gt=now,
    ).order_by("ends_at")[:6]

    stats = {
        "contests": Contest.objects.filter(status=Contest.Status.CLOSED).count(),
        "votes": Vote.objects.count(),
        "contestants": Contestant.objects.count(),
    }

    return render(request, "voting/home.html", {
        "open_contests": open_contests,
        "stats": stats,
    })


def contest_list(request):
    now = timezone.now()
    open_contests = Contest.objects.filter(
        status=Contest.Status.OPEN,
        starts_at__lte=now,
        ends_at__gt=now,
    ).order_by("ends_at")
    past_contests = Contest.objects.filter(
        status=Contest.Status.CLOSED,
    ).order_by("-closed_at")[:10]

    return render(request, "voting/contest_list.html", {
        "open_contests": open_contests,
        "past_contests": past_contests,
    })


def contest_detail(request, contest_id):
    contest = get_object_or_404(Contest, pk=contest_id)
    leaderboard = contest.contestants.order_by("-vote_count", "name")
    user_voted = (
        request.user.is_authenticated
        and contest.votes.filter(voter=request.user).exists()
    )

    return render(request, "voting/contest_detail.html", {
        "contest": contest,
        "leaderboard": leaderboard,
        "is_open": contest.is_open_now(),
        "user_voted": user_voted,
    })


def contest_results(request, contest_id):
    contest = get_object_or_404(Contest, pk=contest_id)
    if contest.status != Contest.Status.CLOSED:
        return redirect("voting:contest_detail", contest_id=contest.id)

    leaderboard = contest.contestants.order_by("-vote_count", "name")
    winners = list(contest.winners())
    total_votes = leaderboard.aggregate(total=Sum("vote_count"))["total"] or 0

    # Open Graph image: prefer winner's photo, fall back to contest cover
    og_image = None
    if winners and winners[0].image:
        og_image = request.build_absolute_uri(winners[0].image.url)
    elif contest.image:
        og_image = request.build_absolute_uri(contest.image.url)

    if len(winners) == 1:
        share_text = f"{winners[0].name} won {contest.title} with {winners[0].vote_count} votes on Crowna!"
    elif len(winners) > 1:
        names = ", ".join(w.name for w in winners)
        share_text = f"Joint winners in {contest.title}: {names} — see results on Crowna."
    else:
        share_text = f"{contest.title} — final results on Crowna."

    return render(request, "voting/contest_results.html", {
        "contest": contest,
        "leaderboard": leaderboard,
        "winners": winners,
        "total_votes": total_votes,
        "share_url": request.build_absolute_uri(),
        "share_text": share_text,
        "og_image": og_image,
    })


def contestant_detail(request, contestant_id):
    contestant = get_object_or_404(
        Contestant.objects.select_related("contest"),
        pk=contestant_id,
    )
    contest = contestant.contest

    siblings = contest.contestants.all()
    rank = siblings.filter(vote_count__gt=contestant.vote_count).count() + 1
    total_contestants = siblings.count()
    total_votes = siblings.aggregate(total=Sum("vote_count"))["total"] or 0
    share = round((contestant.vote_count / total_votes) * 100, 1) if total_votes else 0

    user_voted = (
        request.user.is_authenticated
        and contest.votes.filter(voter=request.user).exists()
    )

    return render(request, "voting/contestant_detail.html", {
        "contestant": contestant,
        "contest": contest,
        "rank": rank,
        "total_contestants": total_contestants,
        "total_votes": total_votes,
        "share": share,
        "is_open": contest.is_open_now(),
        "user_voted": user_voted,
    })


@login_required
@require_POST
def cast_vote(request, contest_id, contestant_id):
    contest = get_object_or_404(Contest, pk=contest_id)
    contestant = get_object_or_404(Contestant, pk=contestant_id, contest=contest)

    if not contest.is_open_now():
        return JsonResponse({"error": "Voting is not open for this contest."}, status=403)

    try:
        with transaction.atomic():
            Vote.objects.create(contest=contest, contestant=contestant, voter=request.user)
            Contestant.objects.filter(pk=contestant.pk).update(
                vote_count=F("vote_count") + 1
            )
    except IntegrityError:
        return JsonResponse({"error": "You have already voted in this contest."}, status=409)

    if request.headers.get("Accept", "").startswith("text/html"):
        next_url = request.POST.get("next", "")
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return redirect(next_url)
        return redirect("voting:contest_detail", contest_id=contest.id)

    contestant.refresh_from_db(fields=["vote_count"])
    return JsonResponse({
        "contestant_id": contestant.id,
        "name": contestant.name,
        "vote_count": contestant.vote_count,
    })


class SignupView(CreateView):
    form_class = SignupForm
    template_name = "voting/signup.html"
    success_url = reverse_lazy("voting:home")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("voting:home")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        login(self.request, self.object)
        return response