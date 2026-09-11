# -*- coding: utf-8 -*-
"""quote_keeper.py — 글귀 모음 (EPUB/TXT 하이라이트 자동 아카이브)

EPUB/TXT 리더에서 텍스트를 드래그해 하이라이트(형광펜)를 만들면 코어가 그 즉시
`book_annotations` 테이블에 기록한다 — 이 플러그인은 별도 저장 단계 없이, 그 테이블을
`books`와 조인해서 그대로 읽어 보여주는 "라이브 뷰"다. 그래서:

  - 형광펜을 그으면 → 따로 뭘 누르지 않아도 자동으로 여기에 나타난다.
  - 형광펜을 지우면(리더에서 하이라이트 삭제) → 여기서도 자동으로 사라진다.
  - 이 화면에서 삭제하면 → 실제 하이라이트도 함께 지워진다(같은 레코드이므로).

플러그인 자체 DB를 따로 두지 않고 코어 DB만 읽고 쓰므로, book_annotations와 항상
정확히 일치한다 — 동기화 로직/중복 저장 걱정이 없다.
"""
from flask import session

from plugins.metadata.base import BaseMetadataProvider

MAX_NOTE_LEN = 2000


class QuoteKeeperProvider(BaseMetadataProvider):
    """EPUB/TXT 하이라이트를 자동으로 보여주는 카테고리 레벨 플러그인."""

    id = "quote_keeper"
    name = "글귀 모음"
    is_searchable = False
    config_schema = []

    dashboard_widget = {
        "title": "글귀 모음",
        "subtitle": "최근에 만든 하이라이트",
        "provider": "BookOasis",
        "icon": "fa-solid fa-quote-right",
        "limit": 5,
    }
    category_tab = {
        "title": "글귀 모음",
        "icon": "fa-solid fa-quote-right",
        "order": 92,
        "sessions": "all",
    }

    update_manifest = {
        "enabled": True,
        "provider": "github-raw",
        "raw_base_url": "https://raw.githubusercontent.com/grandfoxx/quote_keeper/master",
        "files": ["quote_keeper.py", "__init__.py", "VERSION", "index.html", "script.js", "style.css"],
        "version_file": "VERSION",
        "version_key": "plugin version",
        "show_sample_update_button": True,
    }

    # ────────────────────────────────────────────────────────────────
    # BaseMetadataProvider 필수 계약
    # ────────────────────────────────────────────────────────────────
    def search(self, db_type, query):
        return []

    def apply(self, db_type, book_id, item_data):
        return False, "글귀 모음 플러그인은 메타데이터 적용을 지원하지 않습니다."

    def _current_user_id(self):
        try:
            return session.get("user_id")
        except RuntimeError:
            return None

    @staticmethod
    def _resolve_cover_url(cover_image):
        if not cover_image:
            return None
        clean = str(cover_image).strip()
        if not clean:
            return None
        if clean.startswith("http://") or clean.startswith("https://") or clean.startswith("/"):
            return clean
        clean = clean.lstrip("/\\")
        if clean.lower().startswith("covers/"):
            clean = clean[len("covers/"):].lstrip("/\\")
        return f"/covers/{clean}" if clean else None

    def _row_to_quote(self, row):
        return {
            "id": row["id"],
            "book_id": row["book_id"],
            "book_title": row["title"],
            "series_name": row["series_name"],
            "cover_image": self._resolve_cover_url(row["cover_image"]),
            "format": row["format"],
            "chapter_idx": row["chapter_idx"],
            "pages_read": row["pages_read"],
            "total_pages": row["total_pages"],
            "quote": row["quote"],
            "note": row["note"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    # ────────────────────────────────────────────────────────────────
    # 대시보드 위젯 — 최근 하이라이트 미리보기
    # ────────────────────────────────────────────────────────────────
    def get_dashboard_data(self, db_type, limit=10):
        user_id = self._current_user_id()
        if not user_id:
            return {"success": True, "items": []}

        gateway = self.get_db_gateway(db_type)
        try:
            rows = gateway.fetch_all(
                """
                SELECT a.id, a.book_id, a.format, a.chapter_idx, a.quote, a.note,
                       UNIX_TIMESTAMP(a.created_at) AS created_at,
                       UNIX_TIMESTAMP(a.updated_at) AS updated_at,
                       b.title, b.series_name, b.cover_image, b.total_pages,
                       up.pages_read
                FROM book_annotations a
                JOIN books b ON b.id = a.book_id
                LEFT JOIN user_progress up ON up.book_id = a.book_id AND up.user_id = a.user_id
                WHERE a.user_id = ? AND COALESCE(b.is_deleted, 0) = 0
                ORDER BY a.created_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            )
        except Exception:
            rows = []

        items = []
        for row in rows:
            quote_text = row["quote"] or ""
            snippet = quote_text if len(quote_text) <= 70 else quote_text[:70].rstrip() + "…"
            items.append(
                {
                    "item_type": "metric",
                    "metric": row["series_name"] or row["title"],
                    "value": f"“{snippet}”",
                    "description": row["title"] if row["series_name"] else None,
                }
            )
        return {"success": True, "items": items}

    # ────────────────────────────────────────────────────────────────
    # 카테고리 전체화면 UI용 RPC 채널
    # (reading_review 샘플과 동일하게 /api/media/context-menu/book/plugins/action 재사용)
    # ────────────────────────────────────────────────────────────────
    def run_context_menu_action(self, db_type, action_id, context):
        handlers = {
            "list_quotes": self._action_list_quotes,
            "update_note": self._action_update_note,
            "delete_quote": self._action_delete_quote,
            "get_stats": self._action_get_stats,
        }
        handler = handlers.get(action_id)
        if not handler:
            return {"success": False, "error": f"지원하지 않는 액션입니다: {action_id}"}

        user_id = self._current_user_id()
        if not user_id:
            return {"success": False, "error": "로그인 세션이 필요합니다."}

        try:
            return handler(db_type, context, user_id)
        except Exception as e:
            return {"success": False, "error": f"처리 중 오류가 발생했습니다: {e}"}

    def _action_list_quotes(self, db_type, context, user_id):
        query = str(context.get("query") or "").strip()
        gateway = self.get_db_gateway(db_type)

        if query:
            like = f"%{query}%"
            rows = gateway.fetch_all(
                """
                SELECT a.id, a.book_id, a.format, a.chapter_idx, a.quote, a.note,
                       UNIX_TIMESTAMP(a.created_at) AS created_at,
                       UNIX_TIMESTAMP(a.updated_at) AS updated_at,
                       b.title, b.series_name, b.cover_image, b.total_pages,
                       up.pages_read
                FROM book_annotations a
                JOIN books b ON b.id = a.book_id
                LEFT JOIN user_progress up ON up.book_id = a.book_id AND up.user_id = a.user_id
                WHERE a.user_id = ? AND COALESCE(b.is_deleted, 0) = 0
                  AND (a.quote LIKE ? OR b.title LIKE ? OR b.series_name LIKE ? OR a.note LIKE ?)
                ORDER BY a.created_at DESC
                """,
                (user_id, like, like, like, like),
            )
        else:
            rows = gateway.fetch_all(
                """
                SELECT a.id, a.book_id, a.format, a.chapter_idx, a.quote, a.note,
                       UNIX_TIMESTAMP(a.created_at) AS created_at,
                       UNIX_TIMESTAMP(a.updated_at) AS updated_at,
                       b.title, b.series_name, b.cover_image, b.total_pages,
                       up.pages_read
                FROM book_annotations a
                JOIN books b ON b.id = a.book_id
                LEFT JOIN user_progress up ON up.book_id = a.book_id AND up.user_id = a.user_id
                WHERE a.user_id = ? AND COALESCE(b.is_deleted, 0) = 0
                ORDER BY a.created_at DESC
                """,
                (user_id,),
            )

        return {"success": True, "items": [self._row_to_quote(r) for r in rows]}

    def _action_update_note(self, db_type, context, user_id):
        annotation_id = context.get("id")
        if not annotation_id:
            return {"success": False, "error": "id가 없습니다."}
        note = str(context.get("note") or "").strip()[:MAX_NOTE_LEN] or None

        gateway = self.get_db_gateway(db_type)
        gateway.execute(
            "UPDATE book_annotations SET note = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND user_id = ?",
            (note, annotation_id, user_id),
        )
        return {"success": True}

    def _action_delete_quote(self, db_type, context, user_id):
        annotation_id = context.get("id")
        if not annotation_id:
            return {"success": False, "error": "id가 없습니다."}

        gateway = self.get_db_gateway(db_type)
        gateway.execute(
            "DELETE FROM book_annotations WHERE id = ? AND user_id = ?",
            (annotation_id, user_id),
        )
        return {"success": True}

    def _action_get_stats(self, db_type, context, user_id):
        gateway = self.get_db_gateway(db_type)

        total_row = gateway.fetch_one(
            """
            SELECT COUNT(*) AS c FROM book_annotations a
            JOIN books b ON b.id = a.book_id
            WHERE a.user_id = ? AND COALESCE(b.is_deleted, 0) = 0
            """,
            (user_id,),
        )
        books_row = gateway.fetch_one(
            """
            SELECT COUNT(DISTINCT COALESCE(NULLIF(b.series_name, ''), b.title)) AS c
            FROM book_annotations a
            JOIN books b ON b.id = a.book_id
            WHERE a.user_id = ? AND COALESCE(b.is_deleted, 0) = 0
            """,
            (user_id,),
        )
        recent_row = gateway.fetch_one(
            """
            SELECT COUNT(*) AS c FROM book_annotations a
            JOIN books b ON b.id = a.book_id
            WHERE a.user_id = ? AND COALESCE(b.is_deleted, 0) = 0
              AND a.created_at >= NOW() - INTERVAL 30 DAY
            """,
            (user_id,),
        )
        stats = {
            "total": (total_row or {}).get("c", 0),
            "books": (books_row or {}).get("c", 0),
            "recent_30d": (recent_row or {}).get("c", 0),
        }
        return {"success": True, "stats": stats}
