"""Multi-tenant scoping helpers.

Each non-superuser **admin** account is its own tenant. Managers and employees
belong to the admin that owns them (``CustomUser.owner``). Every admin-facing
query in the project must be scoped through these helpers so one admin can
never see — or reach by URL — another admin's users or their data.

Rules:
* superuser  -> global (sees everything, no scoping)
* role=admin -> tenant root; sees users whose owner is itself (plus itself)
* manager/employee -> belongs to ``self.owner``'s tenant
"""

from django.db.models import Q

from .models import CustomUser


def tenant_root(user):
    """Return the owning admin for this user's tenant.

    Returns ``None`` for superusers (global / no scoping) and for users with no
    resolvable owner.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return None
    if user.is_superuser:
        return None
    if user.role == "admin":
        return user
    return user.owner


def scoped_user_qs(user, base=None):
    """A CustomUser queryset limited to ``user``'s tenant.

    Superusers get the unfiltered base queryset. A tenant admin gets users they
    own plus their own account. Anyone with no tenant gets an empty queryset.
    """
    qs = base if base is not None else CustomUser.objects.all()
    if user and user.is_superuser:
        return qs
    root = tenant_root(user)
    if root is None:
        return qs.none()
    return qs.filter(Q(owner=root) | Q(pk=root.pk))


def scoped_user_ids(user):
    """List of user PKs visible to ``user`` (used to scope related models)."""
    return list(scoped_user_qs(user).values_list("pk", flat=True))


def in_same_tenant(user, target):
    """True if ``target`` user is visible within ``user``'s tenant."""
    if user and user.is_superuser:
        return True
    if target is None:
        return False
    return scoped_user_qs(user).filter(pk=target.pk).exists()
