"""The lexical arm searches for a question's content words, any of them.

`search_lexical_chunks` used `plainto_tsquery('simple', question)`: every token ANDed,
stop words included, so it matched only a chunk containing all of "how do i restore the
database from a backup". It fired on 1 of the 20 retrieval-eval questions, which made
hybrid search semantic-only for anything phrased as a question — and made EV-1's proof
run (zero the lexical weight, watch the gate go red) impossible, since a weight on an
arm that never fires changes nothing.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.utils.scope import ALL_WORKSPACES
from src.utils.text import content_terms

pytestmark = pytest.mark.unit


class TestContentTerms:
    def test_a_question_keeps_its_topic_words_only(self):
        assert content_terms("How do I restore the database from a backup?") == [
            "restore", "database", "backup",
        ]

    def test_repeats_collapse_and_first_appearance_order_is_kept(self):
        assert content_terms("backup the backup, then restore") == ["backup", "then", "restore"]

    def test_words_in_other_scripts_stay_whole(self):
        assert content_terms("Één offerte voor zoëven") == ["één", "offerte", "voor", "zoëven"]

    def test_digits_and_codenames_survive(self):
        assert content_terms("Why did migration 0017 add RLS?") == ["migration", "0017", "add", "rls"]

    def test_tsquery_operators_cannot_get_through(self):
        """The terms are joined into a to_tsquery expression, so nothing else may survive."""
        assert content_terms("a & b | !c <-> 'd' (e):*") == []
        assert content_terms("alpha_beta & gamma|delta") == ["alpha", "beta", "gamma", "delta"]

    def test_a_question_of_only_stop_words_has_no_terms(self):
        assert content_terms("how is it the") == []


def _connected_cursor(rows=()):
    cursor = MagicMock()
    cursor.fetchall.return_value = list(rows)
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    return conn, cursor


class TestTheQuerySent:
    def test_the_terms_are_ored_into_to_tsquery(self):
        from src import db as db_module

        conn, cursor = _connected_cursor()
        with (
            patch.object(db_module.db, "is_connected", True),
            patch.object(db_module.db, "get_connection") as get_conn,
        ):
            get_conn.return_value.__enter__.return_value = conn
            db_module.db.search_lexical_chunks(
                "How do I restore the database from a backup?", top_k=5, scope=ALL_WORKSPACES
            )

        sql, params = cursor.execute.call_args.args
        assert "to_tsquery('simple', %s)" in sql
        assert "plainto_tsquery" not in sql
        assert params[0] == "restore | database | backup"

    def test_only_stop_words_never_reaches_the_database(self):
        from src import db as db_module

        with (
            patch.object(db_module.db, "is_connected", True),
            patch.object(db_module.db, "get_connection") as get_conn,
        ):
            assert db_module.db.search_lexical_chunks("how is it the", scope=ALL_WORKSPACES) == []
            get_conn.assert_not_called()
