from typing import List, Optional
from fastapi import APIRouter, HTTPException, status, Query
from sqlmodel import select, func, or_
from app.api.deps import SessionDep, CurrentUser
from app.models import (
    Bookmark,
    BookmarkCreate,
    BookmarkRead,
    BookmarkUpdate,
    Tag,
    BookmarkTag,
)

router = APIRouter()


@router.post("/", response_model=BookmarkRead, status_code=status.HTTP_201_CREATED)
def create_bookmark(
    bookmark_in: BookmarkCreate, db: SessionDep, current_user: CurrentUser
):
    """Create a new bookmark"""
    # Create bookmark
    bookmark = Bookmark(
        **bookmark_in.model_dump(exclude={"tags"}), user_id=current_user.id
    )
    db.add(bookmark)
    db.commit()
    db.refresh(bookmark)

    # Handle tags
    if bookmark_in.tags:
        for tag_name in bookmark_in.tags:
            # Get or create tag
            tag = db.exec(select(Tag).where(Tag.name == tag_name.lower())).first()
            if not tag:
                tag = Tag(name=tag_name.lower())
                db.add(tag)
                db.commit()
                db.refresh(tag)

            # Create bookmark-tag relationship
            bookmark_tag = BookmarkTag(bookmark_id=bookmark.id, tag_id=tag.id)
            db.add(bookmark_tag)

        db.commit()
        # Refresh the bookmark again to load the new tag relationships
        db.refresh(bookmark)

    # Exclude the 'tags' relationship from the model_dump
    return BookmarkRead(
        **bookmark.model_dump(exclude={"tags"}),
        tags=[tag.name for tag in bookmark.tags],
    )


@router.get("/", response_model=List[BookmarkRead])
def read_bookmarks(
    db: SessionDep,
    current_user: CurrentUser,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    search: Optional[str] = Query(None, description="Search in title and description"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    is_favorite: Optional[bool] = Query(None, description="Filter favorites only"),
):
    """Get user's bookmarks with optional filtering"""
    # Base query
    query = select(Bookmark).where(Bookmark.user_id == current_user.id)

    # Apply filters
    if search:
        search_filter = or_(
            Bookmark.title.contains(search),
            Bookmark.description.contains(search),
            Bookmark.url.contains(search),
        )
        query = query.where(search_filter)

    if is_favorite is not None:
        query = query.where(Bookmark.is_favorite == is_favorite)

    if tag:
        # Join with tags
        query = query.join(BookmarkTag).join(Tag).where(Tag.name == tag.lower())

    # Execute query
    bookmarks = db.exec(
        query.order_by(Bookmark.created_at.desc()).offset(skip).limit(limit)
    ).all()

    # Format response with tags
    result = []
    for bookmark in bookmarks:
        bookmark_dict = bookmark.model_dump()
        bookmark_dict["tags"] = [tag.name for tag in bookmark.tags]
        result.append(BookmarkRead(**bookmark_dict))

    return result


@router.get("/stats")
def get_bookmark_stats(db: SessionDep, current_user: CurrentUser):
    """Get user's bookmark statistics"""
    total = db.exec(
        select(func.count(Bookmark.id)).where(Bookmark.user_id == current_user.id)
    ).one()

    favorites = db.exec(
        select(func.count(Bookmark.id))
        .where(Bookmark.user_id == current_user.id)
        .where(Bookmark.is_favorite)
    ).one()

    # Get tag counts
    tag_counts = db.exec(
        select(Tag.name, func.count(BookmarkTag.bookmark_id))
        .join(BookmarkTag)
        .join(Bookmark)
        .where(Bookmark.user_id == current_user.id)
        .group_by(Tag.name)
        .order_by(func.count(BookmarkTag.bookmark_id).desc())
    ).all()

    return {
        "total_bookmarks": total,
        "total_favorites": favorites,
        "tags": [{"name": name, "count": count} for name, count in tag_counts],
    }


@router.get("/{bookmark_id}", response_model=BookmarkRead)
def read_bookmark(bookmark_id: int, db: SessionDep, current_user: CurrentUser):
    """Get bookmark by ID"""
    bookmark = db.get(Bookmark, bookmark_id)

    if not bookmark:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Bookmark not found"
        )

    # Check ownership
    if bookmark.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this bookmark",
        )

    return BookmarkRead(
        **bookmark.model_dump(), tags=[tag.name for tag in bookmark.tags]
    )


@router.patch("/{bookmark_id}", response_model=BookmarkRead)
def update_bookmark(
    bookmark_id: int,
    bookmark_in: BookmarkUpdate,
    db: SessionDep,
    current_user: CurrentUser,
):
    """Update bookmark"""
    # Get bookmark
    bookmark = db.get(Bookmark, bookmark_id)

    if not bookmark:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Bookmark not found"
        )

    # Check ownership
    if bookmark.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this bookmark",
        )

    # Update fields
    update_data = bookmark_in.model_dump(exclude_unset=True)

    # Handle tags separately
    if "tags" in update_data:
        new_tags = update_data.pop("tags")

        # Remove existing tags
        db.exec(select(BookmarkTag).where(BookmarkTag.bookmark_id == bookmark_id)).all()
        for bt in db.exec(
            select(BookmarkTag).where(BookmarkTag.bookmark_id == bookmark_id)
        ).all():
            db.delete(bt)

        # Add new tags
        for tag_name in new_tags:
            tag = db.exec(select(Tag).where(Tag.name == tag_name.lower())).first()
            if not tag:
                tag = Tag(name=tag_name.lower())
                db.add(tag)
                db.commit()
                db.refresh(tag)

            bookmark_tag = BookmarkTag(bookmark_id=bookmark.id, tag_id=tag.id)
            db.add(bookmark_tag)

    # Update other fields
    for field, value in update_data.items():
        setattr(bookmark, field, value)

    from datetime import datetime

    bookmark.updated_at = datetime.utcnow()

    db.add(bookmark)
    db.commit()
    db.refresh(bookmark)

    return BookmarkRead(
        **bookmark.model_dump(), tags=[tag.name for tag in bookmark.tags]
    )


@router.delete("/{bookmark_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bookmark(bookmark_id: int, db: SessionDep, current_user: CurrentUser):
    """Delete bookmark"""
    bookmark = db.get(Bookmark, bookmark_id)

    if not bookmark:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Bookmark not found"
        )

    # Check ownership
    if bookmark.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this bookmark",
        )

    db.delete(bookmark)
    db.commit()
