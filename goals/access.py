"""Row-level access: Super Users see all; Managers/Project Leads see their reporting tree; employees see their own."""
from django.db.models import Q

from .models import Goal, TeamMember


def member_of(user):
    return getattr(user, "member", None) if user.is_authenticated else None


def scope_ids(user):
    """None = unrestricted; otherwise set of TeamMember ids the user may see."""
    if user.is_superuser:
        return None
    m = member_of(user)
    return m.subtree_ids() if m else set()


def role_of(user):
    if user.is_superuser:
        return "Super User"
    m = member_of(user)
    if m and m.is_manager:
        return "Manager / Lead"
    return "Employee" if m else "No access"


def visible_goals(user, qs=None):
    qs = Goal.objects.all() if qs is None else qs
    ids = scope_ids(user)
    if ids is None:
        return qs
    return qs.filter(Q(member_id__in=ids) | Q(project_lead_id__in=ids))


def visible_members(user, qs=None):
    qs = TeamMember.objects.all() if qs is None else qs
    ids = scope_ids(user)
    return qs if ids is None else qs.filter(pk__in=ids)


def access(request):
    """Context processor."""
    u = request.user
    return {"user_role": role_of(u) if u.is_authenticated else "", "me": member_of(u)}
