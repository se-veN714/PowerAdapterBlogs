from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from padif.models import Annotation, AnnotationReply, Branch, Document, Version
from padif.services import (BranchError, archive_branch, commit_document_version,
                            create_branch, create_document_from_upload, effective_head,
                            publish_branch)


def make_document(user):
    return create_document_from_upload(user=user, upload=SimpleUploadedFile("draft.md", b"# Draft\n\nFirst."), title="Draft", commit_message="Initial").document


class BranchingTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="writer", email="writer@example.test", password="test-pass", is_active=True)
        self.user.user_permissions.add(Permission.objects.get(codename="use_padif"))
        self.document = make_document(self.user)
        self.initial = self.document.current_version
        self.branch = create_branch(document_id=self.document.pk, user=self.user, name="rewrite", fork_from_version_id=self.initial.pk)
        self.client.force_login(self.user)

    def commit(self, branch=None, base=None, content="Changed."):
        return commit_document_version(document_id=self.document.pk, user=self.user, branch_id=(branch or self.branch).pk,
            base_version_id=base, content=content, commit_message="Revision", version_kind="patch").version

    def publish(self, source, base=None, **extra):
        return publish_branch(document_id=self.document.pk, branch_id=self.branch.pk, user=self.user,
            commit_message="Ready", version_kind="minor", base_version_id=base or self.initial.pk,
            source_version_id=source.pk, confirm_replace=extra.get("confirm", True))

    def test_empty_branch_and_independent_history(self):
        self.assertEqual(effective_head(self.branch), self.initial)
        self.assertEqual(self.branch.versions.count(), 0)
        main = self.document.branches.get(is_default=True)
        alternate = self.commit(base=self.initial.pk)
        primary = self.commit(branch=main, base=self.initial.pk, content="Main edits.")
        self.assertEqual(alternate.semantic_version, primary.semantic_version)
        self.assertEqual(alternate.parent, self.initial)
        self.assertEqual(self.commit(base=alternate.pk).parent, alternate)
        self.document.refresh_from_db()
        self.assertEqual(self.document.current_version, primary)

    def test_stale_commit_does_not_write(self):
        self.commit()
        before = Version.objects.count()
        with self.assertRaises(BranchError) as caught:
            self.commit(base=self.initial.pk)
        self.assertEqual(caught.exception.error_code, "STALE_BASE_VERSION")
        self.assertEqual(Version.objects.count(), before)

    def test_publish_preserves_source_and_rejects_retries(self):
        source = self.commit()
        annotation = Annotation.objects.create(version=source, author=self.user, kind="question", body="Why?", start_line=1, end_line=1)
        result = self.publish(source)
        self.assertEqual(result.version.content, source.content)
        self.assertEqual(result.version.parent, self.initial)
        self.assertTrue(result.version.branch.is_default)
        self.assertIn("publish(branch=rewrite):", result.version.commit_message)
        self.assertEqual(annotation.version_id, source.pk)
        self.assertEqual(effective_head(self.branch), source)
        with self.assertRaises(BranchError):
            self.publish(source)
        next_source = self.commit(base=source.pk)
        self.assertEqual(next_source.parent, source)
        self.publish(next_source, base=result.version.pk)

    def test_publish_checks_both_heads_and_confirmation(self):
        first = self.commit()
        newer = self.commit(base=first.pk)
        with self.assertRaises(BranchError) as caught:
            self.publish(first)
        self.assertEqual(caught.exception.error_code, "STALE_SOURCE_VERSION")
        with self.assertRaises(BranchError):
            self.publish(newer, confirm=False)
        main = self.document.branches.get(is_default=True)
        self.commit(branch=main)
        with self.assertRaises(BranchError) as caught:
            self.publish(newer)
        self.assertEqual(caught.exception.error_code, "STALE_BASE_VERSION")

    def test_archive_preserves_all_rows_and_references(self):
        source = self.commit()
        child = create_branch(document_id=self.document.pk, user=self.user, name="child", fork_from_version_id=source.pk)
        child_version = self.commit(branch=child)
        note = Annotation.objects.create(version=source, author=self.user, kind="question", body="Why?", start_line=1, end_line=1)
        AnnotationReply.objects.create(annotation=note, author=self.user, body="Because.")
        counts = (Version.objects.count(), Annotation.objects.count(), AnnotationReply.objects.count())
        first = archive_branch(document_id=self.document.pk, branch_id=self.branch.pk, user=self.user)
        repeated = archive_branch(document_id=self.document.pk, branch_id=self.branch.pk, user=self.user)
        self.assertEqual(first.archived_at, repeated.archived_at)
        child_version.refresh_from_db()
        self.assertEqual(child_version.parent, source)
        self.assertEqual(counts, (Version.objects.count(), Annotation.objects.count(), AnnotationReply.objects.count()))
        with self.assertRaises(BranchError):
            self.commit()
        with self.assertRaises(BranchError):
            self.publish(source)
        create_branch(document_id=self.document.pk, user=self.user, name="from-archived", fork_from_version_id=source.pk)

    def test_constraints_and_input_validation(self):
        main = self.document.branches.get(is_default=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Branch.objects.create(document=self.document, name="another", is_default=True, created_by=self.user)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Version.objects.create(document=self.document, branch=main, content="Duplicate", semantic_version="1.0.0", commit_message="Duplicate", version_kind="patch", created_by=self.user)
        for name in ("main", "rewrite", "Bad Name", "x" * 65):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                create_branch(document_id=self.document.pk, user=self.user, name=name, fork_from_version_id=self.initial.pk)
        other = make_document(self.user)
        with self.assertRaises(ValidationError):
            create_branch(document_id=self.document.pk, user=self.user, name="cross", fork_from_version_id=other.current_version_id)
        with self.assertRaises(ValidationError):
            Version(document=other, branch=main, parent=self.initial).clean()
        with self.assertRaises(BranchError):
            archive_branch(document_id=self.document.pk, branch_id=main.pk, user=self.user)
        with self.assertRaises(BranchError):
            self.publish(self.initial)

    def test_view_context_upload_and_stale_editor(self):
        url = reverse("padif:document_detail", args=[self.document.pk])
        response = self.client.get(url, {"branch": "rewrite"})
        self.assertEqual(response.context["current_version"], self.initial)
        self.assertEqual(response.context["selected_branch"], self.branch)
        self.assertContains(response, "尚无分支提交")
        self.assertEqual(self.client.get(url, {"branch": "missing"}).status_code, 404)
        response = self.client.post(reverse("padif:upload_version", args=[self.document.pk]), {
            "branch_id": self.branch.pk, "base_version_id": self.initial.pk,
            "markdown_file": SimpleUploadedFile("next.md", b"New branch manuscript."),
            "commit_message": "Upload", "version_kind": "patch"})
        self.assertRedirects(response, url + "?branch=rewrite", fetch_redirect_response=False)
        response = self.client.post(reverse("padif:commit_version", args=[self.document.pk]), {
            "branch_id": self.branch.pk, "base_version_id": self.initial.pk,
            "content": "Unsaved draft", "commit_message": "Still here", "version_kind": "patch"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.context["commit_form"].data["content"], "Unsaved draft")
        self.assertEqual(response.context["selected_branch"], self.branch)

    def test_publish_confirmation_and_archive_pages_do_not_write_on_get(self):
        source = self.commit()
        publish_url = reverse("padif:publish_branch", args=[self.document.pk, self.branch.pk])
        before = Version.objects.count()
        response = self.client.get(publish_url)
        self.assertContains(response, "主线正文将采用分支整稿")
        self.assertEqual(response.context["source_head"], source)
        self.assertEqual(Version.objects.count(), before)
        self.commit()
        response = self.client.post(publish_url, {"commit_message": "Publish", "version_kind": "patch", "base_version_id": self.initial.pk, "source_version_id": source.pk, "confirm_replace": "on"})
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "重新读取版本", status_code=409)
        archive_url = reverse("padif:archive_branch", args=[self.document.pk, self.branch.pk])
        self.client.get(archive_url)
        self.branch.refresh_from_db()
        self.assertIsNone(self.branch.archived_at)
        self.client.post(archive_url)
        response = self.client.get(reverse("padif:document_detail", args=[self.document.pk]), {"branch": "rewrite"})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "添加版本</button>")
        self.assertContains(response, "全屏预览")

    def test_new_routes_require_login_permission_and_csrf(self):
        urls = [reverse("padif:create_branch", args=[self.document.pk]), reverse("padif:publish_branch", args=[self.document.pk, self.branch.pk]), reverse("padif:archive_branch", args=[self.document.pk, self.branch.pk])]
        anonymous = Client()
        for url in urls:
            self.assertEqual(anonymous.post(url).status_code, 302)
        outsider = get_user_model().objects.create_user(username="outsider", email="outsider@example.test", password="test-pass", is_active=True)
        anonymous.force_login(outsider)
        for url in urls:
            self.assertEqual(anonymous.post(url).status_code, 403)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        for url in urls:
            self.assertEqual(csrf_client.post(url).status_code, 403)


class BranchMigrationTests(TransactionTestCase):
    def setUp(self):
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([("padif", "0004_annotationreply")])
        self.apps = self.executor.loader.project_state([("padif", "0004_annotationreply")]).apps

    def tearDown(self):
        # Remove only the anomalous fixture before restoring the latest schema.
        Document = self.apps.get_model("padif", "Document")
        for document in Document.objects.all():
            latest = self.apps.get_model("padif", "Version").objects.filter(document_id=document.pk).order_by("-id").first()
            document.current_version_id = latest.pk if latest else None
            document.save()
        MigrationExecutor(connection).migrate([("padif", "0005_branching")])
        super().tearDown()

    def old_document(self):
        user = get_user_model().objects.create_user(username="old-writer", email="old@example.test", password="test-pass", is_active=True)
        document = self.apps.get_model("padif", "Document").objects.create(title="Legacy", created_by_id=user.pk)
        Version = self.apps.get_model("padif", "Version")
        first = Version.objects.create(document_id=document.pk, created_by_id=user.pk, content="Original", semantic_version="1.0.0", commit_message="First", version_kind="major")
        second = Version.objects.create(document_id=document.pk, created_by_id=user.pk, content="Second", semantic_version="1.0.1", commit_message="Second", version_kind="patch")
        document.current_version_id = second.pk
        document.save()
        return user, document, first, second

    def test_historical_data_backfills_without_changing_annotations(self):
        user, document, first, second = self.old_document()
        note = self.apps.get_model("padif", "Annotation").objects.create(version_id=first.pk, author_id=user.pk, kind="question", body="Old note", start_line=1, end_line=1)
        self.apps.get_model("padif", "AnnotationReply").objects.create(annotation_id=note.pk, author_id=user.pk, body="Old reply")
        empty = self.apps.get_model("padif", "Document").objects.create(title="Empty", created_by_id=user.pk)
        MigrationExecutor(connection).migrate([("padif", "0005_branching")])
        self.assertEqual(Document.objects.get(pk=document.pk).current_version_id, second.pk)
        self.assertEqual(Version.objects.get(pk=second.pk).parent_id, first.pk)
        self.assertEqual(Version.objects.get(pk=first.pk).content, "Original")
        self.assertEqual(Branch.objects.filter(document_id=empty.pk, is_default=True).count(), 1)
        self.assertEqual(AnnotationReply.objects.get().body, "Old reply")

    def test_anomalous_current_version_aborts_migration(self):
        _, document, first, _ = self.old_document()
        document.current_version_id = first.pk
        document.save()
        with self.assertRaisesRegex(RuntimeError, "current_version"):
            MigrationExecutor(connection).migrate([("padif", "0005_branching")])
        self.assertFalse(MigrationExecutor(connection).loader.applied_migrations.get(("padif", "0005_branching")))


@skipUnless(connection.vendor == "postgresql", "PostgreSQL row locks required")
class BranchConcurrencyTests(TransactionTestCase):
    def test_same_base_can_only_commit_once(self):
        user = get_user_model().objects.create_user(username="parallel", email="parallel@example.test", password="test-pass", is_active=True)
        document = make_document(user)
        branch = document.branches.get(is_default=True)
        barrier = Barrier(2)
        def submit(index):
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=user.pk)
                barrier.wait(timeout=10)
                try:
                    commit_document_version(document_id=document.pk, branch_id=branch.pk, user=actor,
                        content=f"Revision {index}", commit_message="Parallel", version_kind="patch", base_version_id=document.current_version_id)
                    return "ok"
                except BranchError as exc:
                    return exc.error_code
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(submit, [1, 2]))
        self.assertCountEqual(outcomes, ["ok", "STALE_BASE_VERSION"])
        self.assertEqual(document.versions.count(), 2)

class VersionRailTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="rail-writer", email="rail@example.test", password="test-pass", is_active=True)
        self.user.user_permissions.add(Permission.objects.get(codename="use_padif"))
        self.document = make_document(self.user)
        self.main = self.document.branches.get(is_default=True)
        self.initial = self.document.current_version
        self.url = reverse("padif:document_detail", args=[self.document.pk])
        self.client.force_login(self.user)

    def fork(self, name, source=None):
        return create_branch(document_id=self.document.pk, user=self.user, name=name,
                             fork_from_version_id=(source or self.initial).pk)

    def commit(self, branch, message="Update"):
        return commit_document_version(document_id=self.document.pk, branch_id=branch.pk, user=self.user,
            content=message, commit_message=message, version_kind="patch").version

    def cards(self, response):
        return [card for row in response.context["rail_rows"] for card in row["branches"]] + response.context["rail_unattached"]

    def test_three_recent_branches_and_main_always_visible(self):
        branches = [self.fork(f"draft-{index}") for index in range(5)]
        response = self.client.get(self.url)
        cards = self.cards(response)
        self.assertEqual({card["branch"].pk for card in cards}, {item.pk for item in branches[-3:]})
        self.assertFalse(any(card["selected"] for card in cards))
        self.assertContains(response, 'data-worldline-branch=', count=3)
        self.assertContains(response, 'data-expanded="true"', count=0)
        self.assertEqual(response.context["rail_main"], self.main)
        self.assertContains(response, "main · 主线")
        self.assertEqual(response.context["rail_branch_total"], 5)
        self.assertContains(response, "全部分支 · 5")

    def test_older_current_branch_is_pinned_and_only_it_expands(self):
        old = self.fork("old-selected")
        first = self.commit(old, "Only selected history is visible")
        self.commit(old, "Second selected revision")
        others = [self.fork(f"newer-{index}") for index in range(4)]
        self.commit(others[0], "Hidden unselected commit message")
        response = self.client.get(self.url, {"branch": old.name})
        cards = self.cards(response)
        self.assertEqual(len(cards), 3)
        self.assertEqual([card["branch"].pk for card in cards if card["selected"]], [old.pk])
        self.assertContains(response, 'data-expanded="true"', count=1)
        self.assertContains(response, 'data-worldline-branch=', count=3)
        self.assertContains(response, first.commit_message)
        self.assertNotContains(response, "Hidden unselected commit message")
        self.assertEqual(response.context["selected_branch"], old)

    def test_recent_activity_uses_commits_and_ignores_archived_unless_selected(self):
        old = self.fork("old")
        others = [self.fork(f"recent-{index}") for index in range(3)]
        self.commit(old)
        response = self.client.get(self.url)
        self.assertIn(old.pk, {card["branch"].pk for card in self.cards(response)})
        archive_branch(document_id=self.document.pk, branch_id=old.pk, user=self.user)
        response = self.client.get(self.url)
        self.assertNotIn(old.pk, {card["branch"].pk for card in self.cards(response)})
        self.assertContains(response, "已归档")
        response = self.client.get(self.url, {"branch": old.name})
        cards = self.cards(response)
        self.assertEqual(len(cards), 3)
        self.assertIn(old.pk, {card["branch"].pk for card in cards})
        self.assertContains(response, "已归档 · 当前查看")
        self.assertNotContains(response, "审阅并采用此稿")
        self.assertTrue(all(item.pk != self.main.pk for item in others))

    def test_main_window_keeps_true_old_fork_anchor_and_full_history_is_optional(self):
        branch = self.fork("old-fork")
        main_versions = [self.initial] + [self.commit(self.main, f"Main {index}") for index in range(8)]
        response = self.client.get(self.url, {"branch": branch.name})
        rows = response.context["rail_rows"]
        self.assertEqual(len([row for row in rows if not row["anchor_only"]]), 5)
        anchor = next(row for row in rows if row["version"].pk == self.initial.pk)
        self.assertTrue(anchor["anchor_only"])
        self.assertEqual(anchor["branches"][0]["branch"], branch)
        self.assertContains(response, "较早分叉点")
        self.assertContains(response, "查看完整主线历史")
        full = self.client.get(self.url, {"branch": branch.name, "history": "all"})
        self.assertEqual(len(full.context["rail_rows"]), len(main_versions))
        self.assertFalse(any(row["anchor_only"] for row in full.context["rail_rows"]))
        self.assertContains(full, "收起较早历史")

    def test_nested_branch_anchors_to_main_ancestor_and_empty_branch_stays_readable(self):
        parent = self.fork("parent")
        parent_version = self.commit(parent)
        child = self.fork("child", parent_version)
        response = self.client.get(self.url, {"branch": child.name})
        row = next(row for row in response.context["rail_rows"] if row["version"].pk == self.initial.pk)
        self.assertIn(child.pk, {card["branch"].pk for card in row["branches"]})
        self.assertContains(response, "尚无分支提交")
        self.assertEqual(response.context["current_version"], parent_version)
        self.assertContains(response, 'data-expanded="true"', count=1)
        self.assertContains(response, 'name="branch_id" value="' + str(child.pk) + '"')

    def test_no_branches_renders_main_and_long_labels_are_escaped(self):
        response = self.client.get(self.url)
        self.assertEqual(len(self.cards(response)), 0)
        self.assertContains(response, "尚无分支")
        branch = self.fork("long-name-" + "a" * 54)
        self.commit(branch, '<script>alert("test")</script>')
        response = self.client.get(self.url, {"branch": branch.name})
        self.assertContains(response, '&lt;script&gt;alert(')
        self.assertNotContains(response, '<script>alert("test")</script>')

class UploadTargetBranchTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="upload-target", email="upload-target@example.test", password="test-pass", is_active=True)
        self.user.user_permissions.add(Permission.objects.get(codename="use_padif"))
        self.document = make_document(self.user)
        self.main = self.document.branches.get(is_default=True)
        self.branch = create_branch(document_id=self.document.pk, user=self.user, name="rewrite", fork_from_version_id=self.document.current_version_id)
        self.client.force_login(self.user)
        self.url = reverse("padif:upload_version", args=[self.document.pk])

    def payload(self, form, target):
        import json
        return {"branch_id": self.main.pk, "target_branch": target.pk,
                "branch_bases": json.dumps(form.initial["branch_bases"]),
                "base_version_id": self.document.current_version_id,
                "markdown_file": SimpleUploadedFile("revision.md", b"Branch-only upload"),
                "commit_message": "Upload", "version_kind": "patch"}

    def test_upload_target_works_without_js_and_preserves_four_cells(self):
        response = self.client.get(reverse("padif:document_detail", args=[self.document.pk]))
        form = response.context["upload_form"]
        self.assertContains(response, 'name="target_branch"')
        self.assertContains(response, 'class="main-add-version__cell"', count=3)
        self.assertContains(response, 'class="main-add-version__cell main-add-version__submit"', count=1)
        response = self.client.post(self.url, self.payload(form, self.branch))
        self.assertEqual(response.status_code, 302)
        self.assertIn("branch=rewrite", response.url)
        latest = self.branch.versions.get()
        self.assertEqual(latest.content, "Branch-only upload")
        self.document.refresh_from_db()
        self.assertEqual(latest.parent_id, self.document.current_version_id)

    def test_changed_target_head_returns_conflict_using_render_time_baseline(self):
        response = self.client.get(reverse("padif:document_detail", args=[self.document.pk]))
        payload = self.payload(response.context["upload_form"], self.branch)
        commit_document_version(document_id=self.document.pk, branch_id=self.branch.pk, user=self.user,
                                content="Newer branch", commit_message="Race", version_kind="patch")
        before = Version.objects.count()
        response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Version.objects.count(), before)
        self.assertEqual(response.context["selected_branch"], self.branch)
        self.assertEqual(response.context["upload_form"].data["commit_message"], "Upload")

    def test_target_excludes_archived_and_foreign_document_branches(self):
        response = self.client.get(reverse("padif:document_detail", args=[self.document.pk]))
        form = response.context["upload_form"]
        other = make_document(self.user).branches.get(is_default=True)
        response = self.client.post(self.url, self.payload(form, other))
        self.assertEqual(response.status_code, 400)
        archive_branch(document_id=self.document.pk, branch_id=self.branch.pk, user=self.user)
        response = self.client.post(self.url, self.payload(form, self.branch))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.branch.versions.count(), 0)

    def test_target_requires_a_valid_snapshot_but_legacy_form_still_works(self):
        response = self.client.get(reverse("padif:document_detail", args=[self.document.pk]))
        payload = self.payload(response.context["upload_form"], self.branch)
        payload.pop("branch_bases")
        self.assertEqual(self.client.post(self.url, payload).status_code, 400)
        legacy = {"branch_id": self.branch.pk, "markdown_file": SimpleUploadedFile("legacy.md", b"Legacy upload"),
                  "commit_message": "Legacy", "version_kind": "patch"}
        self.assertEqual(self.client.post(self.url, legacy).status_code, 302)

class WorldlineGraphTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="worldline", email="worldline@example.test", password="test-pass", is_active=True)
        self.user.user_permissions.add(Permission.objects.get(codename="use_padif"))
        self.document = make_document(self.user)
        self.initial = self.document.current_version
        self.main = self.document.branches.get(is_default=True)
        self.branch = create_branch(document_id=self.document.pk, user=self.user, name="opening", fork_from_version_id=self.initial.pk)
        self.client.force_login(self.user)
        self.url = reverse("padif:document_detail", args=[self.document.pk])

    def graph(self, branch="opening"):
        response = self.client.get(self.url, {"branch": branch})
        self.assertEqual(response.status_code, 200)
        return response, response.context["worldlines"]

    def test_parallel_lanes_connect_real_fork_and_advance_upward(self):
        first = commit_document_version(document_id=self.document.pk, branch_id=self.branch.pk, user=self.user,
            content="First experiment", commit_message="First", version_kind="patch").version
        last = commit_document_version(document_id=self.document.pk, branch_id=self.branch.pk, user=self.user,
            content="Second experiment", commit_message="Second", version_kind="minor").version
        response, graph = self.graph()
        nodes = {node["version"].pk: node for node in graph["nodes"]}
        self.assertEqual(nodes[self.initial.pk]["left"], 50)
        self.assertNotEqual(nodes[last.pk]["left"], 50)
        self.assertLess(nodes[last.pk]["top"], nodes[first.pk]["top"])
        self.assertLess(nodes[first.pk]["top"], nodes[self.initial.pk]["top"])
        selected_path = next(path for path in graph["paths"] if path["kind"] == "selected")
        self.assertTrue(selected_path["d"].startswith(f'M 340 {nodes[self.initial.pk]["top"]} '))
        self.assertTrue(selected_path["d"].endswith(f'V {nodes[last.pk]["top"]}'))
        self.assertContains(response, 'data-worldline-layout')
        self.assertContains(response, 'id="padif-version-drawer"')
        self.assertContains(response, 'data-drawer-handle')
        self.assertContains(response, 'data-drawer-close')
        self.assertEqual(sum(head["selected"] for head in graph["heads"]), 1)
        self.assertFalse(next(head for head in graph["heads"] if head["main"])["selected"])
        self.assertEqual(Version.objects.count(), 3)

    def test_empty_branch_labels_and_geometry_stay_inside_canvas(self):
        _, graph = self.graph()
        self.assertEqual(len(graph["heads"]), 2)
        for head in graph["heads"]:
            self.assertGreaterEqual(head["top"], 0)
            self.assertLess(head["top"] + 58, graph["height"])
        self.assertEqual(Version.objects.count(), 1)
        _, main_graph = self.graph("main")
        self.assertTrue(next(head for head in main_graph["heads"] if head["main"])["selected"])

    def test_hidden_source_branch_is_named_instead_of_inventing_a_direct_main_fork(self):
        parent_version = commit_document_version(document_id=self.document.pk, branch_id=self.branch.pk, user=self.user,
            content="Parent", commit_message="Parent", version_kind="patch").version
        child = create_branch(document_id=self.document.pk, user=self.user, name="child", fork_from_version_id=parent_version.pk)
        for index in range(3):
            create_branch(document_id=self.document.pk, user=self.user, name=f"new-{index}", fork_from_version_id=self.initial.pk)
        response, graph = self.graph(child.name)
        self.assertTrue(any("opening" in item["label"] for item in graph["origins"]))
        self.assertContains(response, "源于 opening")
        self.assertLessEqual(sum(not head["main"] for head in graph["heads"]), 3)


    def test_all_visible_branches_show_recent_iterations_without_shuffling_lanes(self):
        branches = [self.branch] + [create_branch(document_id=self.document.pk, user=self.user,
            name=name, fork_from_version_id=self.initial.pk) for name in ("ending", "structure")]
        expected = {}
        for branch in branches:
            own_versions = []
            for index in range(4):
                own_versions.append(commit_document_version(document_id=self.document.pk, branch_id=branch.pk,
                    user=self.user, content=f"{branch.name} revision {index}",
                    commit_message=f"{branch.name} note {index}", version_kind="patch").version)
            expected[branch.pk] = {version.pk for version in own_versions[-3:]}
        before = Version.objects.count()
        response, graph = self.graph("opening")
        for branch in branches:
            nodes = {node["version"].pk for node in graph["nodes"] if node["version"].branch_id == branch.pk}
            self.assertEqual(nodes, expected[branch.pk])
        self.assertLessEqual(graph["height"], 460)
        self.assertContains(response, "opening note 0")
        self.assertNotContains(response, "ending note 0")
        positions = {head["branch"].pk: head["left"] for head in graph["heads"]}
        _, switched = self.graph("ending")
        self.assertEqual(positions, {head["branch"].pk: head["left"] for head in switched["heads"]})
        self.assertEqual(Version.objects.count(), before)
