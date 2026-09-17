from pathlib import Path
import pytest

from services.desktop.filesystem import FilesystemService
from services.desktop.policy import DesktopSecurityPolicy, SecurityPolicyError


@pytest.fixture
def isolated_service(tmp_path: Path):
    """Provides a FilesystemService configured exclusively with temporary sandbox roots."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    desktop = sandbox / "Desktop"
    desktop.mkdir()

    documents = sandbox / "Documents"
    documents.mkdir()

    downloads = sandbox / "Downloads"
    downloads.mkdir()

    workspace = sandbox / "ECHO_Workspace"
    workspace.mkdir()

    policy = DesktopSecurityPolicy(
        authorized_roots=[desktop, documents, downloads, workspace],
        include_default_roots=False,
    )
    service = FilesystemService(policy=policy)

    return {
        "service": service,
        "policy": policy,
        "desktop": desktop,
        "documents": documents,
        "downloads": downloads,
        "workspace": workspace,
        "sandbox": sandbox,
        "outside": tmp_path / "outside",
    }


# 10. Read allowed file
def test_read_allowed_file(isolated_service):
    service: FilesystemService = isolated_service["service"]
    docs: Path = isolated_service["documents"]

    test_file = docs / "sample.txt"
    test_file.write_text("ECHO desktop test content", encoding="utf-8")

    content = service.read_file(test_file)
    assert content == "ECHO desktop test content"


def test_read_nonexistent_file_fails(isolated_service):
    service: FilesystemService = isolated_service["service"]
    docs: Path = isolated_service["documents"]

    with pytest.raises(FileNotFoundError):
        service.read_file(docs / "missing.txt")


# 11. List authorized directory
def test_list_authorized_directory(isolated_service):
    service: FilesystemService = isolated_service["service"]
    docs: Path = isolated_service["documents"]

    (docs / "file1.txt").write_text("1")
    (docs / "file2.txt").write_text("22")
    (docs / "subfolder").mkdir()
    (docs / ".hidden").write_text("hidden")

    entries = service.list_folder(docs, include_hidden=False)
    names = [e["name"] for e in entries]

    assert "file1.txt" in names
    assert "file2.txt" in names
    assert "subfolder" in names
    assert ".hidden" not in names

    # With include_hidden=True
    entries_all = service.list_folder(docs, include_hidden=True)
    all_names = [e["name"] for e in entries_all]
    assert ".hidden" in all_names


# 12. Create file
def test_create_file(isolated_service):
    service: FilesystemService = isolated_service["service"]
    workspace: Path = isolated_service["workspace"]

    target = workspace / "new_file.txt"
    res = service.create_file(target, content="Hello ECHO", overwrite=False)

    assert res["status"] == "created"
    assert res["verified"] is True
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == "Hello ECHO"


# 13. Create folder
def test_create_folder(isolated_service):
    service: FilesystemService = isolated_service["service"]
    docs: Path = isolated_service["documents"]

    target_dir = docs / "projects" / "ai_system"
    res = service.create_folder(target_dir, exist_ok=False)

    assert res["status"] == "created"
    assert res["verified"] is True
    assert target_dir.is_dir()


# 14. Duplicate create rejected
def test_duplicate_create_rejected(isolated_service):
    service: FilesystemService = isolated_service["service"]
    workspace: Path = isolated_service["workspace"]

    target = workspace / "existing.txt"
    target.write_text("original content")

    # Creating again with overwrite=False must fail
    with pytest.raises(FileExistsError):
        service.create_file(target, content="new content", overwrite=False)

    # Creating folder again with exist_ok=False must fail
    folder = workspace / "folder"
    folder.mkdir()
    with pytest.raises(FileExistsError):
        service.create_folder(folder, exist_ok=False)


# 15. Copy file
def test_copy_file(isolated_service):
    service: FilesystemService = isolated_service["service"]
    docs: Path = isolated_service["documents"]
    downloads: Path = isolated_service["downloads"]

    src = docs / "report.txt"
    src.write_text("report data")

    dst = downloads / "report_copy.txt"
    res = service.copy_file(src, dst, overwrite=False)

    assert res["status"] == "copied"
    assert res["verified"] is True
    assert src.is_file()
    assert dst.is_file()
    assert dst.read_text() == "report data"


# 16. Rename file
def test_rename_file(isolated_service):
    service: FilesystemService = isolated_service["service"]
    docs: Path = isolated_service["documents"]

    src = docs / "old_name.txt"
    src.write_text("rename me")

    dst = docs / "new_name.txt"
    res = service.rename_file(src, dst, overwrite=False)

    assert res["status"] == "renamed"
    assert res["verified"] is True
    assert not src.exists()
    assert dst.is_file()
    assert dst.read_text() == "rename me"


# 17. Move file
def test_move_file(isolated_service):
    service: FilesystemService = isolated_service["service"]
    desktop: Path = isolated_service["desktop"]
    docs: Path = isolated_service["documents"]

    src = desktop / "move_me.txt"
    src.write_text("moving file")

    dst = docs / "archived" / "moved.txt"
    res = service.move_file(src, dst, overwrite=False)

    assert res["status"] == "moved"
    assert res["verified"] is True
    assert not src.exists()
    assert dst.is_file()
    assert dst.read_text() == "moving file"


# 18. Destination outside sandbox rejected
def test_destination_outside_sandbox_rejected(isolated_service):
    service: FilesystemService = isolated_service["service"]
    docs: Path = isolated_service["documents"]
    outside: Path = isolated_service["outside"]

    src = docs / "valid.txt"
    src.write_text("valid content")

    dst_outside = outside / "escaped.txt"

    with pytest.raises(SecurityPolicyError):
        service.copy_file(src, dst_outside)

    with pytest.raises(SecurityPolicyError):
        service.move_file(src, dst_outside)

    with pytest.raises(SecurityPolicyError):
        service.rename_file(src, dst_outside)


# 22. Overwrite protection
def test_overwrite_protection(isolated_service):
    service: FilesystemService = isolated_service["service"]
    workspace: Path = isolated_service["workspace"]

    file1 = workspace / "target.txt"
    file1.write_text("initial")

    # Fails by default
    with pytest.raises(FileExistsError):
        service.create_file(file1, "updated", overwrite=False)
    assert file1.read_text() == "initial"

    # Succeeds with overwrite=True
    res = service.create_file(file1, "updated", overwrite=True)
    assert res["status"] == "overwritten"
    assert file1.read_text() == "updated"


def test_delete_file_and_empty_directory(isolated_service):
    service: FilesystemService = isolated_service["service"]
    workspace: Path = isolated_service["workspace"]

    # Delete single file
    target_file = workspace / "to_delete.txt"
    target_file.write_text("bye")
    res_file = service.delete_file(target_file)
    assert res_file["status"] == "deleted"
    assert not target_file.exists()

    # Delete empty folder
    empty_dir = workspace / "empty_dir"
    empty_dir.mkdir()
    res_dir = service.delete_file(empty_dir)
    assert res_dir["status"] == "deleted"
    assert not empty_dir.exists()


def test_delete_non_empty_directory_prohibited(isolated_service):
    service: FilesystemService = isolated_service["service"]
    workspace: Path = isolated_service["workspace"]

    non_empty = workspace / "non_empty_dir"
    non_empty.mkdir()
    (non_empty / "child.txt").write_text("child")

    with pytest.raises(ValueError) as exc_info:
        service.delete_file(non_empty)

    assert "Recursive directory deletion is prohibited" in str(exc_info.value)
    assert non_empty.exists()
