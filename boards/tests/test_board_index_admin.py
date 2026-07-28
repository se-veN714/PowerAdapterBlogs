from django.contrib.admin.sites import AdminSite
from django.test import SimpleTestCase
from django.utils.safestring import SafeData

from boards.admin import BoardAdmin
from boards.models import Board


class BoardAdminDisplayTests(SimpleTestCase):
    def test_glitch_color_preview_returns_safe_escaped_html(self):
        board = Board(name="Unsafe", slug="unsafe", glitch_color="<script>")
        model_admin = BoardAdmin(Board, AdminSite())

        preview = model_admin.glitch_color_preview(board)

        self.assertIsInstance(preview, SafeData)
        self.assertIn("<span", preview)
        self.assertNotIn("<script>", preview)
        self.assertIn("&lt;script&gt;", preview)
