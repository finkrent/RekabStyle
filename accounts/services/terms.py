"""Acceptance of the Website Rules and Regulations (legal evidence)."""
from django.conf import settings

from accounts.models import TermsAcceptance


def current_terms_version():
    """The rules version currently published to clients."""
    return str(settings.TERMS["CURRENT_VERSION"])


def record_terms_acceptance(user, *, national_id, ip_address=None, user_agent=""):
    """Store that `user` accepted the current rules with this national ID.

    Call within the transaction that creates the user so a user can never exist
    without the matching consent record.
    """
    return TermsAcceptance.objects.create(
        user=user,
        national_id=national_id,
        terms_version=current_terms_version(),
        ip_address=ip_address,
        user_agent=(user_agent or "")[:255],
    )
