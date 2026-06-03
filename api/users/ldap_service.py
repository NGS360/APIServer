"""
LDAP service for user directory lookup.
Provides user search against an LDAP directory with graceful error handling.
"""
import logging

from ldap3 import Server, Connection, ALL, SUBTREE
from ldap3.core.exceptions import LDAPException

from core.config import get_settings
from api.users.models import UserSearchResult

logger = logging.getLogger(__name__)


def get_ldap_connection() -> Connection | None:
    """
    Create and return an authenticated LDAP connection.

    Returns:
        An active LDAP Connection, or None if connection fails.
    """
    settings = get_settings()

    if not settings.LDAP_ENABLED or not settings.LDAP_SERVER:
        return None

    try:
        server = Server(
            settings.LDAP_SERVER,
            port=settings.LDAP_PORT,
            use_ssl=settings.LDAP_USE_SSL,
            get_info=ALL,
            connect_timeout=settings.LDAP_TIMEOUT,
        )

        conn = Connection(
            server,
            user=settings.LDAP_BIND_DN,
            password=settings.LDAP_BIND_PASSWORD,
            auto_bind=True,
            read_only=True,
            receive_timeout=settings.LDAP_TIMEOUT,
        )
        return conn
    except LDAPException as e:
        logger.warning(f"Failed to connect to LDAP server: {e}")
        return None
    except Exception as e:
        logger.warning(f"Unexpected error connecting to LDAP: {e}")
        return None


def search_users_ldap(query: str, limit: int = 20) -> list[UserSearchResult] | None:
    """
    Search for users in the LDAP directory.

    Args:
        query: Search string to match against user attributes.
        limit: Maximum number of results to return.

    Returns:
        List of UserSearchResult if LDAP is available and search succeeds.
        None if LDAP is unavailable or search fails (signals fallback to DB).
    """
    settings = get_settings()

    if not settings.LDAP_ENABLED:
        return None

    conn = get_ldap_connection()
    if conn is None:
        return None

    try:
        # Build search filter from template
        search_filter = settings.LDAP_USER_SEARCH_FILTER.format(query=query)
        attributes = [
            a.strip() for a in settings.LDAP_USER_ATTRIBUTES.split(",")
        ]

        conn.search(
            search_base=settings.LDAP_BASE_DN,
            search_filter=search_filter,
            search_scope=SUBTREE,
            attributes=attributes,
            size_limit=limit,
        )

        results = []
        for entry in conn.entries:
            # Safely extract attributes with fallbacks
            username = _get_entry_attr(entry, "uid") or _get_entry_attr(entry, "cn") or ""
            email = _get_entry_attr(entry, "mail")
            full_name = _get_entry_attr(entry, "displayName") or _get_entry_attr(entry, "cn")
            department = _get_entry_attr(entry, "department")
            title = _get_entry_attr(entry, "title")

            results.append(UserSearchResult(
                username=username,
                email=email,
                full_name=full_name,
                department=department,
                title=title,
                source="ldap",
            ))

        return results
    except LDAPException as e:
        logger.error(f"LDAP search failed: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error during LDAP search: {e}")
        return None
    finally:
        try:
            conn.unbind()
        except Exception:
            pass


def _get_entry_attr(entry, attr_name: str) -> str | None:
    """
    Safely get an attribute value from an LDAP entry.

    Args:
        entry: ldap3 Entry object
        attr_name: Attribute name to retrieve

    Returns:
        String value of the attribute, or None if not present.
    """
    try:
        value = getattr(entry, attr_name, None)
        if value is not None:
            str_value = str(value)
            # ldap3 returns "[]" for empty attributes
            if str_value and str_value != "[]":
                return str_value
    except Exception:
        pass
    return None
