from fastapi.testclient import TestClient
from sqlmodel import Session
from app.models import User, Bookmark

# The 'client' and 'test_user' fixtures are used from your conftest.py


def test_create_bookmark(client: TestClient, test_user: User):
    """Test creating a bookmark for the current user."""
    response = client.post(
        "/api/v1/bookmarks/",
        # The header is required, but the token value doesn't matter for now
        headers={"Authorization": "Bearer test"},
        json={"url": "https://test.com", "title": "Test Bookmark", "tags": ["testing"]},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Test Bookmark"
    assert data["user_id"] == test_user.id
    assert data["tags"] == ["testing"]


def test_read_bookmarks(client: TestClient, session: Session, test_user: User):
    """Test reading a list of bookmarks."""
    b1 = Bookmark(url="https://site1.com", title="Site 1", user_id=test_user.id)
    b2 = Bookmark(url="https://site2.com", title="Site 2", user_id=test_user.id)
    session.add_all([b1, b2])
    session.commit()

    response = client.get(
        "/api/v1/bookmarks/", headers={"Authorization": "Bearer test"}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    # Assuming default sort is created_at descending
    assert data[0]["title"] == "Site 2"
    assert data[1]["title"] == "Site 1"


def test_update_bookmark(client: TestClient, session: Session, test_user: User):
    """Test updating a user's own bookmark."""
    bookmark = Bookmark(
        url="https://original.com", title="Original Title", user_id=test_user.id
    )
    session.add(bookmark)
    session.commit()
    session.refresh(bookmark)

    response = client.patch(
        f"/api/v1/bookmarks/{bookmark.id}",
        headers={"Authorization": "Bearer test"},
        json={"title": "Updated Title", "is_favorite": True},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Updated Title"
    assert data["is_favorite"] is True


def test_delete_bookmark(client: TestClient, session: Session, test_user: User):
    """Test deleting a user's own bookmark."""
    bookmark = Bookmark(
        url="https://todelete.com", title="To Delete", user_id=test_user.id
    )
    session.add(bookmark)
    session.commit()
    session.refresh(bookmark)

    response = client.delete(
        f"/api/v1/bookmarks/{bookmark.id}", headers={"Authorization": "Bearer test"}
    )
    assert response.status_code == 204

    # Verify it's gone
    deleted_bookmark = session.get(Bookmark, bookmark.id)
    assert deleted_bookmark is None


def test_fail_to_access_other_user_bookmark(
    client: TestClient, session: Session, test_user: User
):
    """Test that a user cannot access another user's bookmark."""
    # The authenticated user is 'testuser'
    other_user = User(
        username="otheruser", email="other@example.com", hashed_password="hash"
    )
    session.add(other_user)
    session.commit()
    session.refresh(other_user)

    other_bookmark = Bookmark(
        url="https://secret.com", title="Secret", user_id=other_user.id
    )
    session.add(other_bookmark)
    session.commit()
    session.refresh(other_bookmark)

    # 'testuser' tries to access other_bookmark
    response = client.get(
        f"/api/v1/bookmarks/{other_bookmark.id}",
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 403  # Forbidden
