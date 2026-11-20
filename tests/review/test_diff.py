# Filename: test_diff.py
# Created on: November 20, 2026
# Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

from farejador.review.diff import FileStatus, LineKind, parse_diff

MODIFIED = """\
diff --git a/src/app.py b/src/app.py
index 111..222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,4 +1,5 @@
 import os
-import sys
+import json
+import re

 def main():
@@ -20,3 +21,3 @@ def helper():
     a = 1
-    b = 2
+    b = 3
     return a
\\ No newline at end of file
"""


def test_added_removed_and_context_lines_get_the_right_numbers() -> None:
    (file,) = parse_diff(MODIFIED)
    assert (file.path, file.old_path, file.status) == (
        "src/app.py",
        "src/app.py",
        FileStatus.MODIFIED,
    )
    by_kind = [(line.kind, line.old_line, line.new_line, line.text) for line in file.lines]
    assert by_kind[0][0] is LineKind.HUNK
    assert (LineKind.CONTEXT, 1, 1, "import os") in by_kind
    assert (LineKind.REMOVED, 2, None, "import sys") in by_kind
    assert (LineKind.ADDED, None, 2, "import json") in by_kind
    assert (LineKind.ADDED, None, 3, "import re") in by_kind
    # the blank context line is "" in some diffs and " " in others; both are context
    assert (LineKind.CONTEXT, 3, 4, "") in by_kind
    assert (LineKind.CONTEXT, 4, 5, "def main():") in by_kind


def test_second_hunk_restarts_numbering_and_marker_line_is_ignored() -> None:
    (file,) = parse_diff(MODIFIED)
    assert file.added_lines == frozenset({2, 3, 22})
    assert all("No newline" not in line.text for line in file.lines)


def test_new_file_has_status_added_and_numbers_from_one() -> None:
    diff = """\
diff --git a/new.py b/new.py
new file mode 100644
index 0000000..abc
--- /dev/null
+++ b/new.py
@@ -0,0 +1,2 @@
+first
+second
"""
    (file,) = parse_diff(diff)
    assert file.status is FileStatus.ADDED
    assert file.path == "new.py"
    assert file.added_lines == frozenset({1, 2})


def test_deleted_file_uses_the_old_path() -> None:
    diff = """\
diff --git a/old.py b/old.py
deleted file mode 100644
index abc..0000000
--- a/old.py
+++ /dev/null
@@ -1,2 +0,0 @@
-gone
-gone too
"""
    (file,) = parse_diff(diff)
    assert file.status is FileStatus.DELETED
    assert file.path == "old.py"
    assert file.added_lines == frozenset()


def test_rename_with_changes_tracks_both_paths() -> None:
    diff = """\
diff --git a/old/name.py b/new/name.py
similarity index 90%
rename from old/name.py
rename to new/name.py
index 111..222 100644
--- a/old/name.py
+++ b/new/name.py
@@ -1,2 +1,2 @@
 keep
-before
+after
"""
    (file,) = parse_diff(diff)
    assert file.status is FileStatus.RENAMED
    assert (file.old_path, file.path) == ("old/name.py", "new/name.py")
    assert file.added_lines == frozenset({2})


def test_pure_rename_has_no_lines() -> None:
    diff = """\
diff --git a/a.py b/b.py
similarity index 100%
rename from a.py
rename to b.py
"""
    (file,) = parse_diff(diff)
    assert (file.status, file.path, file.lines) == (FileStatus.RENAMED, "b.py", [])


def test_binary_files_are_flagged() -> None:
    diff = """\
diff --git a/img.png b/img.png
index 111..222 100644
Binary files a/img.png and b/img.png differ
diff --git a/blob.dat b/blob.dat
GIT binary patch
literal 10
"""
    first, second = parse_diff(diff)
    assert first.is_binary and second.is_binary
    assert first.lines == [] and second.lines == []


def test_multiple_files_are_split() -> None:
    diff = (
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x\n+y\n"
        "diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n@@ -5 +5 @@\n-p\n+q\n"
    )
    files = parse_diff(diff)
    assert [f.path for f in files] == ["a.py", "b.py"]
    assert files[1].added_lines == frozenset({5})


def test_a_removed_line_that_looks_like_a_header_is_still_content() -> None:
    diff = (
        "diff --git a/a.sql b/a.sql\n--- a/a.sql\n+++ b/a.sql\n"
        "@@ -1,2 +1,1 @@\n--- comment\n keep\n"
    )
    (file,) = parse_diff(diff)
    assert file.lines[1].kind is LineKind.REMOVED
    assert file.lines[1].text == "-- comment"


def test_empty_and_garbage_input_give_no_files() -> None:
    assert parse_diff("") == []
    assert parse_diff("this is not a diff\nat all\n") == []


def test_unreadable_section_header_is_skipped() -> None:
    diff = "diff --git broken header\n+x\ndiff --git a/ok.py b/ok.py\n@@ -1 +1 @@\n+y\n"
    assert [f.path for f in parse_diff(diff)] == ["ok.py"]


def test_quoted_paths_are_unquoted() -> None:
    diff = (
        'diff --git "a/sp ace.py" "b/sp ace.py"\n--- "a/sp ace.py"\n'
        '+++ "b/sp ace.py"\n@@ -1 +1 @@\n+x\n'
    )
    (file,) = parse_diff(diff)
    assert file.path == "sp ace.py"
