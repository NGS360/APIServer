"""
Tests for /users/search endpoint and user search services.
"""
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient
from sqlmodel import Session

from api.auth.models import User
from api.users.models import UserSearchResult
from api.users.services import search_users, search_users_db


def _mock_app_settings(settings_dict):
    """Create a mock for app_settings with typed getters."""
    mock = MagicMock()
    mock.get.side_effect = lambda key, default=None: settings_dict.get(
        key, default
    )
    mock.get_bool.side_effect = lambda key, default=False: (
        settings_dict.get(key, str(default)).lower().strip()
        in ("true", "1", "yes")
        if settings_dict.get(key) is not None
        and settings_dict.get(key).strip() != ""
        else default
    )
    mock.get_int.side_effect = lambda key, default=0: (
        int(settings_dict[key])
        if key in settings_dict and settings_dict[key].strip() != ""
        else default
    )
    return mock


# --- Route Tests ---


class TestUserSearchRoute:
    """Tests for the /api/v1/users/search endpoint"""

    def test_search_requires_authentication(self, unauthenticated_client: TestClient):
        """Unauthenticated requests should be rejected"""
        response = unauthenticated_client.get(
            "/api/v1/users/search", params={"q": "john"}
        )
        assert response.status_code == 401

    def test_search_requires_min_query_length(self, client: TestClient):
        """Query must be at least 2 characters"""
        response = client.get("/api/v1/users/search", params={"q": "j"})
        assert response.status_code == 422

    def test_search_requires_query_param(self, client: TestClient):
        """Query parameter is required"""
        response = client.get("/api/v1/users/search")
        assert response.status_code == 422

    def test_search_returns_empty_when_no_users(self, client: TestClient):
        """Search returns empty results when no users match"""
        response = client.get(
            "/api/v1/users/search", params={"q": "nonexistent"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["data"] == []
        assert data["count"] == 0
        assert data["query"] == "nonexistent"
        assert data["source"] == "database"

    def test_search_finds_users_by_username(self, client: TestClient, session: Session):
        """Search matches users by username"""
        user = User(
            username="johndoe",
            email="john@example.com",
            full_name="John Doe",
            is_active=True,
            is_verified=True,
        )
        session.add(user)
        session.commit()

        response = client.get("/api/v1/users/search", params={"q": "john"})
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["data"][0]["username"] == "johndoe"
        assert data["data"][0]["email"] == "john@example.com"
        assert data["data"][0]["full_name"] == "John Doe"
        assert data["data"][0]["source"] == "database"
        assert data["source"] == "database"

    def test_search_finds_users_by_email(self, client: TestClient, session: Session):
        """Search matches users by email"""
        user = User(
            username="jsmith",
            email="jane.smith@company.com",
            full_name="Jane Smith",
            is_active=True,
        )
        session.add(user)
        session.commit()

        response = client.get(
            "/api/v1/users/search", params={"q": "jane.smith"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["data"][0]["username"] == "jsmith"

    def test_search_finds_users_by_full_name(
        self, client: TestClient, session: Session
    ):
        """Search matches users by full name"""
        user = User(
            username="bwilson",
            email="bob@example.com",
            full_name="Bob Wilson",
            is_active=True,
        )
        session.add(user)
        session.commit()

        response = client.get("/api/v1/users/search", params={"q": "Wilson"})
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["data"][0]["username"] == "bwilson"

    def test_search_excludes_inactive_users(
        self, client: TestClient, session: Session
    ):
        """Inactive users should not appear in search results"""
        active_user = User(
            username="active_user",
            email="active@example.com",
            full_name="Active User",
            is_active=True,
        )
        inactive_user = User(
            username="inactive_user",
            email="inactive@example.com",
            full_name="Inactive User",
            is_active=False,
        )
        session.add(active_user)
        session.add(inactive_user)
        session.commit()

        response = client.get("/api/v1/users/search", params={"q": "user"})
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["data"][0]["username"] == "active_user"

    def test_search_respects_limit_parameter(
        self, client: TestClient, session: Session
    ):
        """Limit parameter restricts number of results"""
        for i in range(5):
            user = User(
                username=f"testuser{i}",
                email=f"test{i}@example.com",
                full_name=f"Test User {i}",
                is_active=True,
            )
            session.add(user)
        session.commit()

        response = client.get(
            "/api/v1/users/search", params={"q": "testuser", "limit": 2}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2
        assert len(data["data"]) == 2

    def test_search_limit_validation(self, client: TestClient):
        """Limit must be between 1 and 100"""
        # Too low
        response = client.get(
            "/api/v1/users/search", params={"q": "test", "limit": 0}
        )
        assert response.status_code == 422

        # Too high
        response = client.get(
            "/api/v1/users/search", params={"q": "test", "limit": 101}
        )
        assert response.status_code == 422

    def test_search_with_ldap_enabled_and_available(
        self, client: TestClient, session: Session
    ):
        """When LDAP is enabled and available, results come from LDAP"""
        mock_ldap_results = [
            UserSearchResult(
                username="ldapuser1",
                email="ldap1@corp.com",
                full_name="LDAP User One",
                department="Engineering",
                title="Developer",
                source="ldap",
            )
        ]

        mock_settings = _mock_app_settings({"LDAP_ENABLED": "true"})

        with patch(
            "api.users.services.search_users_ldap",
            return_value=mock_ldap_results,
        ), patch(
            "api.users.services.app_settings", mock_settings
        ):
            response = client.get(
                "/api/v1/users/search", params={"q": "ldapuser"}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["source"] == "ldap"
        assert data["count"] == 1
        assert data["data"][0]["username"] == "ldapuser1"
        assert data["data"][0]["department"] == "Engineering"
        assert data["data"][0]["title"] == "Developer"

    def test_search_falls_back_to_db_when_ldap_unavailable(
        self, client: TestClient, session: Session
    ):
        """When LDAP is enabled but unavailable, falls back to database"""
        # Add a user to the database
        user = User(
            username="dbuser",
            email="dbuser@example.com",
            full_name="DB User",
            is_active=True,
        )
        session.add(user)
        session.commit()

        mock_settings = _mock_app_settings({"LDAP_ENABLED": "true"})

        with patch(
            "api.users.services.search_users_ldap",
            return_value=None,  # None means LDAP unavailable
        ), patch(
            "api.users.services.app_settings", mock_settings
        ):
            response = client.get(
                "/api/v1/users/search", params={"q": "dbuser"}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["source"] == "database"
        assert data["count"] == 1
        assert data["data"][0]["username"] == "dbuser"


# --- Service Unit Tests ---


class TestSearchUsersDB:
    """Unit tests for search_users_db service function"""

    def test_search_by_username(self, session: Session):
        """Finds users matching username"""
        user = User(
            username="alice",
            email="alice@example.com",
            full_name="Alice Smith",
            is_active=True,
        )
        session.add(user)
        session.commit()

        results = search_users_db(session, "alice")
        assert len(results) == 1
        assert results[0].username == "alice"
        assert results[0].source == "database"

    def test_search_by_email(self, session: Session):
        """Finds users matching email"""
        user = User(
            username="bob",
            email="bob@company.org",
            full_name="Bob Jones",
            is_active=True,
        )
        session.add(user)
        session.commit()

        results = search_users_db(session, "company.org")
        assert len(results) == 1
        assert results[0].username == "bob"

    def test_search_by_full_name(self, session: Session):
        """Finds users matching full name"""
        user = User(
            username="carol",
            email="carol@example.com",
            full_name="Carol Williams",
            is_active=True,
        )
        session.add(user)
        session.commit()

        results = search_users_db(session, "Williams")
        assert len(results) == 1
        assert results[0].username == "carol"

    def test_search_case_insensitive(self, session: Session):
        """Search is case-insensitive"""
        user = User(
            username="Dave",
            email="dave@example.com",
            full_name="Dave Brown",
            is_active=True,
        )
        session.add(user)
        session.commit()

        results = search_users_db(session, "dave")
        assert len(results) == 1
        assert results[0].username == "Dave"

    def test_search_excludes_inactive(self, session: Session):
        """Does not return inactive users"""
        user = User(
            username="inactive",
            email="inactive@example.com",
            full_name="Inactive Person",
            is_active=False,
        )
        session.add(user)
        session.commit()

        results = search_users_db(session, "inactive")
        assert len(results) == 0

    def test_search_respects_limit(self, session: Session):
        """Respects the limit parameter"""
        for i in range(10):
            user = User(
                username=f"user{i}",
                email=f"user{i}@example.com",
                is_active=True,
            )
            session.add(user)
        session.commit()

        results = search_users_db(session, "user", limit=3)
        assert len(results) == 3

    def test_search_no_match(self, session: Session):
        """Returns empty list when no users match"""
        user = User(
            username="someone",
            email="someone@example.com",
            is_active=True,
        )
        session.add(user)
        session.commit()

        results = search_users_db(session, "zzzzz")
        assert len(results) == 0


class TestSearchUsersOrchestration:
    """Unit tests for the search_users orchestration function"""

    def test_ldap_disabled_uses_database(self, session: Session):
        """When LDAP is disabled, uses database directly"""
        user = User(
            username="dbonly",
            email="dbonly@example.com",
            full_name="DB Only",
            is_active=True,
        )
        session.add(user)
        session.commit()

        mock_settings = _mock_app_settings({"LDAP_ENABLED": "false"})

        with patch("api.users.services.app_settings", mock_settings):
            result = search_users(session, "dbonly")

        assert result.source == "database"
        assert result.count == 1
        assert result.data[0].username == "dbonly"

    def test_ldap_enabled_and_available(self, session: Session):
        """When LDAP is enabled and returns results, uses LDAP"""
        mock_results = [
            UserSearchResult(
                username="ldapuser",
                email="ldap@corp.com",
                full_name="LDAP User",
                department="IT",
                title="Admin",
                source="ldap",
            )
        ]

        mock_settings = _mock_app_settings({"LDAP_ENABLED": "true"})

        with patch(
            "api.users.services.search_users_ldap",
            return_value=mock_results,
        ), patch("api.users.services.app_settings", mock_settings):
            result = search_users(session, "ldapuser")

        assert result.source == "ldap"
        assert result.count == 1
        assert result.data[0].username == "ldapuser"
        assert result.data[0].department == "IT"

    def test_ldap_enabled_but_unavailable_falls_back(self, session: Session):
        """When LDAP is enabled but returns None, falls back to database"""
        user = User(
            username="fallback",
            email="fallback@example.com",
            full_name="Fallback User",
            is_active=True,
        )
        session.add(user)
        session.commit()

        mock_settings = _mock_app_settings({"LDAP_ENABLED": "true"})

        with patch(
            "api.users.services.search_users_ldap",
            return_value=None,
        ), patch("api.users.services.app_settings", mock_settings):
            result = search_users(session, "fallback")

        assert result.source == "database"
        assert result.count == 1
        assert result.data[0].username == "fallback"

    def test_ldap_returns_empty_list(self, session: Session):
        """When LDAP returns empty list (not None), uses that result"""
        # Add a user to DB that matches - should NOT be returned
        # because LDAP returned successfully (just empty)
        user = User(
            username="testuser",
            email="test@example.com",
            is_active=True,
        )
        session.add(user)
        session.commit()

        mock_settings = _mock_app_settings({"LDAP_ENABLED": "true"})

        with patch(
            "api.users.services.search_users_ldap",
            return_value=[],  # Empty list means LDAP worked, just no matches
        ), patch("api.users.services.app_settings", mock_settings):
            result = search_users(session, "testuser")

        assert result.source == "ldap"
        assert result.count == 0
        assert result.data == []

    def test_query_passed_through(self, session: Session):
        """Query string is included in response"""
        mock_settings = _mock_app_settings({"LDAP_ENABLED": "false"})

        with patch("api.users.services.app_settings", mock_settings):
            result = search_users(session, "searchterm")

        assert result.query == "searchterm"


# --- LDAP Service Unit Tests ---


class TestLDAPService:
    """Unit tests for the LDAP service functions"""

    def test_search_returns_none_when_disabled(self):
        """Returns None when LDAP is not enabled"""
        from api.users.ldap_service import search_users_ldap

        mock_settings = _mock_app_settings({"LDAP_ENABLED": "false"})

        with patch("api.users.ldap_service.app_settings", mock_settings):
            result = search_users_ldap("test")

        assert result is None

    def test_search_returns_none_on_connection_failure(self):
        """Returns None when LDAP connection fails"""
        from api.users.ldap_service import search_users_ldap

        mock_settings = _mock_app_settings({
            "LDAP_ENABLED": "true",
            "LDAP_SERVER": "ldap://fake",
        })

        with patch(
            "api.users.ldap_service.get_ldap_connection",
            return_value=None,
        ), patch("api.users.ldap_service.app_settings", mock_settings):
            result = search_users_ldap("test")

        assert result is None

    def test_get_ldap_connection_returns_none_when_disabled(self):
        """get_ldap_connection returns None when LDAP is disabled"""
        from api.users.ldap_service import get_ldap_connection

        mock_settings = _mock_app_settings({"LDAP_ENABLED": "false"})

        with patch("api.users.ldap_service.app_settings", mock_settings):
            result = get_ldap_connection()

        assert result is None

    def test_get_ldap_connection_returns_none_when_no_server(self):
        """get_ldap_connection returns None when no server is configured"""
        from api.users.ldap_service import get_ldap_connection

        mock_settings = _mock_app_settings({"LDAP_ENABLED": "true"})
        # LDAP_SERVER not in settings dict -> get() returns None

        with patch("api.users.ldap_service.app_settings", mock_settings):
            result = get_ldap_connection()

        assert result is None

    def test_search_handles_ldap_exception_gracefully(self):
        """Returns None when LDAP search raises an exception"""
        from api.users.ldap_service import search_users_ldap
        from ldap3.core.exceptions import LDAPException

        mock_conn = MagicMock()
        mock_conn.search.side_effect = LDAPException("Search failed")

        mock_settings = _mock_app_settings({
            "LDAP_ENABLED": "true",
            "LDAP_SERVER": "ldap://fake",
            "LDAP_BASE_DN": "dc=example,dc=com",
            "LDAP_USER_SEARCH_FILTER": "(|(cn=*{query}*)(uid=*{query}*))",
            "LDAP_USER_ATTRIBUTES": "cn,mail,uid,displayName,department,title",
        })

        with patch(
            "api.users.ldap_service.get_ldap_connection",
            return_value=mock_conn,
        ), patch("api.users.ldap_service.app_settings", mock_settings):
            result = search_users_ldap("test")

        assert result is None
        mock_conn.unbind.assert_called_once()

    def test_search_parses_ldap_entries(self):
        """Correctly parses LDAP entry attributes into UserSearchResult"""
        from api.users.ldap_service import search_users_ldap

        # Create mock LDAP entry
        mock_entry = MagicMock()
        mock_entry.uid = "jdoe"
        mock_entry.mail = "jdoe@corp.com"
        mock_entry.displayName = "John Doe"
        mock_entry.cn = "John Doe"
        mock_entry.department = "Engineering"
        mock_entry.title = "Senior Engineer"

        mock_conn = MagicMock()
        mock_conn.entries = [mock_entry]

        mock_settings = _mock_app_settings({
            "LDAP_ENABLED": "true",
            "LDAP_SERVER": "ldap://fake",
            "LDAP_BASE_DN": "dc=example,dc=com",
            "LDAP_USER_SEARCH_FILTER": "(|(cn=*{query}*)(uid=*{query}*))",
            "LDAP_USER_ATTRIBUTES": "cn,mail,uid,displayName,department,title",
        })

        with patch(
            "api.users.ldap_service.get_ldap_connection",
            return_value=mock_conn,
        ), patch("api.users.ldap_service.app_settings", mock_settings):
            result = search_users_ldap("jdoe")

        assert result is not None
        assert len(result) == 1
        assert result[0].username == "jdoe"
        assert result[0].email == "jdoe@corp.com"
        assert result[0].full_name == "John Doe"
        assert result[0].department == "Engineering"
        assert result[0].title == "Senior Engineer"
        assert result[0].source == "ldap"
        mock_conn.unbind.assert_called_once()
