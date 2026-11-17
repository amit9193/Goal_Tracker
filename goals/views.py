from collections import Counter

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from decimal import Decimal, InvalidOperation

from .excel import export_workbook, import_workbook
from .forms import CheckInForm, GoalForm, ImportForm
from .access import visible_goals, visible_members
from .models import QUARTERS, Goal, Team, TeamMember

STATUS_ORDER = ["Complete", "On Track", "Slow", "At Risk", "Not Started"]


def landing(request):
    goals = Goal.objects.exclude(title="")
    ctx = {"stat_goals": goals.count(), "stat_members": TeamMember.objects.count(),
           "stat_complete": goals.filter(status="Complete").count()}
    return render(request, "goals/landing.html", ctx)


@login_required
def dashboard(request):
    team_id = request.GET.get("team", "")
    gqs = visible_goals(request.user).exclude(title="").select_related("member")
    mqs = visible_members(request.user)
    if team_id:
        t = get_object_or_404(Team, pk=team_id)
        scope = [t] + t.descendants()
        gqs, mqs = gqs.filter(member__team__in=scope), mqs.filter(team__in=scope)
    goals = list(gqs)
    total = len(goals)
    counts = Counter(g.status for g in goals)
    q_planned = [round(sum(float(getattr(g, f"{q}_planned") or 0) for g in goals) / (total or 1), 1) for q in QUARTERS]
    q_actual = [round(sum(float(getattr(g, f"{q}_actual") or 0) for g in goals) / (total or 1), 1) for q in QUARTERS]
    members = []
    for m in mqs.prefetch_related("goals"):
        mg = [g for g in m.goals.all() if g.title]
        members.append({"m": m, "count": len(mg),
                        "progress": round(sum(g.progress for g in mg) / len(mg)) if mg else 0,
                        "planned": round(sum(g.planned_progress for g in mg) / len(mg)) if mg else 0,
                        "complete": sum(g.status == "Complete" for g in mg)})
    members.sort(key=lambda x: -x["count"])
    today = timezone.localdate()
    overdue = [g for g in goals if g.target_date and g.target_date < today and g.status != "Complete"]
    ctx = {
        "total": total, "complete": counts["Complete"], "ontrack": counts["On Track"],
        "attention": counts["Slow"] + counts["At Risk"],
        "avg_progress": round(sum(g.progress for g in goals) / total) if total else 0,
        "members": members, "teams": Team.objects.all(), "team_id": team_id, "overdue": overdue[:6], "overdue_count": len(overdue),
        "recent": sorted(goals, key=lambda g: g.updated_at, reverse=True)[:6],
        "chart": {
            "status_labels": STATUS_ORDER, "status_data": [counts[s] for s in STATUS_ORDER],
            "q_planned": q_planned, "q_actual": q_actual,
            "member_labels": [x["m"].name for x in members if x["count"]],
            "member_progress": [x["progress"] for x in members if x["count"]],
            "member_planned": [x["planned"] for x in members if x["count"]],
        },
    }
    return render(request, "goals/dashboard.html", ctx)


@login_required
def goal_list(request):
    qs = visible_goals(request.user).select_related("member", "project_lead")
    q, member, status, show, team = (request.GET.get(k, "") for k in ("q", "member", "status", "show", "team"))
    if show != "all":
        qs = qs.exclude(title="")
    if q:
        qs = qs.filter(Q(goal_id__icontains=q) | Q(title__icontains=q) | Q(description__icontains=q)
                       | Q(member__name__icontains=q) | Q(role__icontains=q))
    if member:
        qs = qs.filter(member_id=member)
    if status:
        qs = qs.filter(status=status)
    if team:
        t = get_object_or_404(Team, pk=team)
        qs = qs.filter(member__team__in=[t] + t.descendants())
    return render(request, "goals/goal_list.html", {
        "goals": qs, "members": visible_members(request.user), "statuses": STATUS_ORDER, "teams": Team.objects.all(),
        "f": {"q": q, "member": member, "status": status, "show": show, "team": team},
    })


@login_required
def goal_detail(request, pk):
    g = get_object_or_404(visible_goals(request.user).select_related("member__team", "project_lead"), pk=pk)
    form = CheckInForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        c = form.save(commit=False)
        c.goal, c.author = g, request.user.get_full_name() or request.user.username
        c.save()
        messages.success(request, "Check-in added.")
        return redirect(g)
    return render(request, "goals/goal_detail.html", {"g": g, "form": form, "checkins": g.checkins.all()})


def _safe_next(request):
    from django.utils.http import url_has_allowed_host_and_scheme
    nxt = request.POST.get("next") or request.GET.get("next")
    return nxt if nxt and url_has_allowed_host_and_scheme(nxt, {request.get_host()}) else None


@login_required
@require_POST
def goal_quick_update(request, pk):
    """Quick progress update from Employees page: status + quarterly actuals."""
    g = get_object_or_404(visible_goals(request.user), pk=pk)
    if request.POST.get("status") in dict(Goal.STATUS_CHOICES):
        g.status = request.POST["status"]
    for q in QUARTERS:
        v = request.POST.get(f"{q}_actual", "").strip()
        try:
            setattr(g, f"{q}_actual", Decimal(v) if v else None)
        except InvalidOperation:
            messages.error(request, f"Invalid {q.upper()} value.")
            return redirect(_safe_next(request) or g)
    g.save()
    messages.success(request, f"Goal {g.goal_id} updated.")
    return redirect(_safe_next(request) or g)


@login_required
@require_POST
def goal_unassign(request, pk):
    g = get_object_or_404(visible_goals(request.user), pk=pk)
    name = g.member
    g.member, g.role = None, ""
    g.save()
    messages.success(request, f"Goal {g.goal_id} removed from {name}.")
    return redirect(_safe_next(request) or "goal_list")


@login_required
@require_POST
def goal_assign(request):
    m = get_object_or_404(visible_members(request.user), pk=request.POST.get("member_id"))
    ids = request.POST.getlist("goal")
    n = 0
    for g in visible_goals(request.user).filter(pk__in=ids):
        g.member, g.role = m, m.role
        g.save()
        n += 1
    messages.success(request, f"{n} goal{'s' if n != 1 else ''} assigned to {m.name}.")
    return redirect(_safe_next(request) or m)


def _next_goal_id():
    nums = [int(g[2:]) for g in Goal.objects.values_list("goal_id", flat=True) if g[2:].isdigit()]
    return f"G-{(max(nums) + 1) if nums else 1:03d}"


@login_required
def goal_form(request, pk=None):
    goal = get_object_or_404(visible_goals(request.user), pk=pk) if pk else None
    me = getattr(request.user, "member", None)
    initial = None
    if not goal:
        m = visible_members(request.user).filter(pk=request.GET.get("member") or 0).first()
        initial = {"goal_id": _next_goal_id(), "member": m,
                   "project_lead": (m.manager if m and m.manager else None) or (me if me and me.is_manager else None)}
    form = GoalForm(request.POST or None, instance=goal, initial=initial)
    form.limit_to(visible_members(request.user))
    if request.method == "POST" and form.is_valid():
        g = form.save(commit=False)
        if g.member and not g.role:
            g.role = g.member.role
        g.save()
        messages.success(request, f"Goal {g.goal_id} saved.")
        return redirect(_safe_next(request) or g)
    return render(request, "goals/goal_form.html", {"form": form, "goal": goal})


@login_required
def goal_delete(request, pk):
    goal = get_object_or_404(visible_goals(request.user), pk=pk)
    if request.method == "POST":
        goal.delete()
        messages.success(request, f"Goal {goal.goal_id} deleted.")
        return redirect(_safe_next(request) or "goal_list")
    return render(request, "goals/confirm_delete.html", {"obj": goal, "kind": "goal", "back": goal.get_absolute_url()})


@login_required
def import_view(request):
    if not request.user.is_superuser:
        messages.error(request, "Only Super Users can import workbooks.")
        return redirect("goal_list")
    form = ImportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            c, u = import_workbook(form.cleaned_data["file"])
            messages.success(request, f"Import complete: {c} created, {u} updated.")
            return redirect("goal_list")
        except Exception as e:  # noqa: BLE001
            messages.error(request, f"Could not read workbook: {e}")
    return render(request, "goals/import.html", {"form": form})


@login_required
def export_view(request):
    wb = export_workbook(visible_goals(request.user).select_related("member__manager", "member__team", "project_lead"))
    resp = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = f'attachment; filename="Goal_Tracker_{timezone.localdate():%Y%m%d}.xlsx"'
    wb.save(resp)
    return resp
