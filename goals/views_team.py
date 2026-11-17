"""People (employees), Teams and Org Tree."""
import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import MemberForm, TeamForm
from decimal import Decimal, InvalidOperation

from .access import visible_goals, visible_members
from .models import QUARTERS, Goal, Team, TeamMember


def _stats_rows(qs):
    return [{"m": m, **m.goal_stats()} for m in qs.select_related("team").prefetch_related("goals")]


@login_required
def people(request):
    """Employee list with search, team filter, add-member modal and inline team assignment."""
    qs = visible_members(request.user)
    q, team, unassigned = request.GET.get("q", ""), request.GET.get("team", ""), request.GET.get("unassigned")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(role__icontains=q) | Q(email__icontains=q))
    if team:
        qs = qs.filter(team_id=team)
    if unassigned:
        qs = qs.filter(team__isnull=True)
    me = getattr(request.user, "member", None)
    form = MemberForm(request.POST or None, user=request.user,
                      initial={"team": team or (me.team_id if me else None), "manager": me})
    if request.method == "POST" and form.is_valid():
        m = form.save()
        messages.success(request, f"{m.name} added{' to ' + m.team.name if m.team else ''}.")
        return redirect(request.get_full_path())
    rows = _stats_rows(qs)
    return render(request, "goals/people.html", {
        "rows": rows, "form": form, "teams": Team.objects.all(), "open_modal": request.method == "POST",
        "f": {"q": q, "team": team, "unassigned": unassigned},
        "statuses": [c[0] for c in Goal.STATUS_CHOICES],
        "free_goals": visible_goals(request.user).filter(member__isnull=True).exclude(title=""),
        "total": visible_members(request.user).count(), "unassigned_count": visible_members(request.user).filter(team__isnull=True).count(),
    })


@login_required
def people_export(request):
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="employees.csv"'
    w = csv.writer(resp)
    w.writerow(["Name", "Role", "Email", "Team", "Goals", "Completed", "Progress %"])
    for r in _stats_rows(visible_members(request.user)):
        m = r["m"]
        w.writerow([m.name, m.role, m.email, m.team or "", r["count"], r["complete"], r["progress"]])
    return resp


@login_required
@require_POST
def assign_team(request):
    """Assign one or many employees to a team (team='' removes from team)."""
    ids = request.POST.getlist("member")
    team = get_object_or_404(Team, pk=request.POST["team"]) if request.POST.get("team") else None
    n = visible_members(request.user).filter(pk__in=ids).update(team=team)
    messages.success(request, f"{n} member{'s' if n != 1 else ''} {'moved to ' + team.name if team else 'removed from team'}.")
    return redirect(request.POST.get("next") or "people")


@login_required
def member_detail(request, pk):
    """Employee profile with inline, bulk-editable goals (status + quarterly planned/actual)."""
    m = get_object_or_404(visible_members(request.user).select_related("team", "manager"), pk=pk)
    goals = [g for g in m.goals.all() if g.title]
    if request.method == "POST":
        valid = dict(Goal.STATUS_CHOICES)
        changed, errors = 0, []
        for g in goals:
            before = (g.status, *[getattr(g, f"{q}_{k}") for q in QUARTERS for k in ("planned", "actual")])
            st = request.POST.get(f"{g.pk}-status")
            if st in valid:
                g.status = st
            for q in QUARTERS:
                for k in ("planned", "actual"):
                    raw = request.POST.get(f"{g.pk}-{q}_{k}")
                    if raw is None:
                        continue
                    raw = raw.strip()
                    try:
                        v = Decimal(raw) if raw else None
                        if v is not None and not (0 <= v <= 100):
                            raise InvalidOperation
                        setattr(g, f"{q}_{k}", v)
                    except InvalidOperation:
                        errors.append(f"{g.goal_id} {q.upper()} {k}")
            after = (g.status, *[getattr(g, f"{q}_{k}") for q in QUARTERS for k in ("planned", "actual")])
            if after != before:
                g.save()
                changed += 1
        if errors:
            messages.error(request, "Ignored invalid values (must be 0–100): " + ", ".join(errors))
        messages.success(request, f"{changed} goal{'s' if changed != 1 else ''} updated." if changed else "No changes to save.")
        return redirect(m)
    return render(request, "goals/member_detail.html", {
        "m": m, "goals": goals, "statuses": list(dict(Goal.STATUS_CHOICES)),
        "free_goals": visible_goals(request.user).filter(member__isnull=True).exclude(title=""), **m.goal_stats()})


@login_required
def member_edit(request, pk):
    m = get_object_or_404(visible_members(request.user), pk=pk)
    form = MemberForm(request.POST or None, instance=m, user=request.user)
    if not request.user.is_superuser and m == getattr(request.user, "member", None):
        form.fields.pop("manager")  # cannot re-parent yourself
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"{m.name} updated.")
        return redirect(m)
    return render(request, "goals/simple_form.html", {"form": form, "title": f"Edit {m.name}", "back": m.get_absolute_url()})


@login_required
def member_delete(request, pk):
    m = get_object_or_404(visible_members(request.user), pk=pk)
    if m == getattr(request.user, "member", None) and not request.user.is_superuser:
        messages.error(request, "You cannot delete yourself.")
        return redirect(m)
    if request.method == "POST":
        m.delete()
        messages.success(request, f"{m.name} removed.")
        return redirect("people")
    return render(request, "goals/confirm_delete.html", {"obj": m, "kind": "employee and all their goals", "back": m.get_absolute_url()})


def _tree(teams_qs):
    """Nested structure: [{'t': team, 'members': [...], 'children': [...]}]"""
    teams = list(teams_qs.select_related("lead").prefetch_related("members__goals"))
    by_parent = {}
    for t in teams:
        by_parent.setdefault(t.parent_id, []).append(t)

    def build(pid):
        out = []
        for t in by_parent.get(pid, []):
            mem = sorted(t.members.all(), key=lambda m: (m != t.lead, m.name))
            out.append({"t": t, "members": [{"m": m, **m.goal_stats()} for m in mem], "children": build(t.pk)})
        return out
    return build(None)


@login_required
def teams(request):
    form = TeamForm(request.POST or None)
    if request.method == "POST" and not request.user.is_superuser:
        messages.error(request, "Only Super Users can create teams.")
        return redirect("teams")
    if request.method == "POST" and form.is_valid():
        t = form.save()
        messages.success(request, f"Team {t.name} created.")
        return redirect("teams")
    cards = []
    for t in Team.objects.select_related("lead", "parent").prefetch_related("members__goals"):
        mem = [m.goal_stats() for m in t.members.all()]
        cards.append({"t": t, "count": len(mem), "goals": sum(x["count"] for x in mem),
                      "progress": round(sum(x["progress"] for x in mem) / len(mem)) if mem else 0,
                      "members": list(t.members.all()[:5])})
    return render(request, "goals/teams.html", {
        "cards": cards, "form": form, "open_modal": request.method == "POST", "tree": _tree(Team.objects.all()),
        "unassigned": visible_members(request.user).filter(team__isnull=True), "view": "cards",
    })


@login_required
def team_detail(request, pk):
    t = get_object_or_404(Team.objects.select_related("lead", "parent"), pk=pk)
    rows = _stats_rows(visible_members(request.user, t.members.all()))
    return render(request, "goals/team_detail.html", {
        "t": t, "rows": rows, "available": visible_members(request.user).exclude(team=t),
        "progress": round(sum(r["progress"] for r in rows) / len(rows)) if rows else 0,
        "goal_count": sum(r["count"] for r in rows), "complete": sum(r["complete"] for r in rows),
        "subteams": t.children.all(),
    })


@login_required
def team_edit(request, pk):
    if not request.user.is_superuser:
        messages.error(request, "Only Super Users can manage teams.")
        return redirect("teams")
    t = get_object_or_404(Team, pk=pk)
    form = TeamForm(request.POST or None, instance=t)
    form.fields["parent"].queryset = Team.objects.exclude(pk__in=[t.pk] + [d.pk for d in t.descendants()])
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Team {t.name} updated.")
        return redirect(t)
    return render(request, "goals/simple_form.html", {"form": form, "title": f"Edit team · {t.name}", "back": t.get_absolute_url()})


@login_required
def team_delete(request, pk):
    if not request.user.is_superuser:
        messages.error(request, "Only Super Users can manage teams.")
        return redirect("teams")
    t = get_object_or_404(Team, pk=pk)
    if request.method == "POST":
        t.delete()
        messages.success(request, f"Team {t.name} deleted. Members are now unassigned.")
        return redirect("teams")
    return render(request, "goals/confirm_delete.html", {"obj": t, "kind": "team (members will be kept, unassigned)", "back": t.get_absolute_url()})


# ---------- Manager hierarchy (Org Tree) ----------
def _org_nodes(members, roots):
    kids = {}
    for m in members:
        kids.setdefault(m.manager_id, []).append(m)

    def build(m, depth=0):
        ch = sorted(kids.get(m.pk, []), key=lambda x: (not kids.get(x.pk), x.name))
        return {"m": m, **m.goal_stats(), "children": [build(c, depth + 1) for c in ch], "depth": depth,
                "team_size": len(m.subtree_ids()) - 1}
    return [build(r) for r in roots]


@login_required
def org(request):
    """Hierarchy: Super Users -> Managers / Project Leads -> Team members."""
    from django.contrib.auth import get_user_model
    members = list(visible_members(request.user).select_related("team", "manager").prefetch_related("goals"))
    ids = {m.pk for m in members}
    if request.user.is_superuser:
        roots = [m for m in members if m.manager_id is None and any(x.manager_id == m.pk for x in members)]
        loose = [m for m in members if m.manager_id is None and m not in roots]
    else:
        me = getattr(request.user, "member", None)
        roots, loose = ([me] if me else []), []
    return render(request, "goals/org.html", {
        "tree": _org_nodes(members, roots), "loose": loose,
        "supers": get_user_model().objects.filter(is_superuser=True) if request.user.is_superuser else [],
        "managers": sum(1 for m in members if any(x.manager_id == m.pk for x in members)),
        "mgr_options": [[m.pk, f"{m.name} — {m.role}" if m.role else m.name] for m in sorted(members, key=lambda x: x.name)],
        "count": len(ids)})


@login_required
@require_POST
def set_manager(request):
    """Re-assign selected members to a manager (drag-free bulk action)."""
    mgr = get_object_or_404(visible_members(request.user), pk=request.POST.get("manager")) if request.POST.get("manager") else None
    if mgr is None and not request.user.is_superuser:
        messages.error(request, "Choose a manager.")
        return redirect(request.POST.get("next") or "org")
    n = 0
    me = getattr(request.user, "member", None)
    for m in visible_members(request.user).filter(pk__in=request.POST.getlist("member")):
        if m == me and not request.user.is_superuser:
            continue
        if mgr and (mgr.pk in m.subtree_ids()):
            continue  # would create a cycle
        m.manager = mgr
        m.save(update_fields=["manager"])
        n += 1
    messages.success(request, f"{n} reporting line{'s' if n != 1 else ''} updated.")
    return redirect(request.POST.get("next") or "org")
