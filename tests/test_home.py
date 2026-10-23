"""Where personal data is read from: this checkout, the main checkout of a git worktree,
or DYNAMICRESUME_HOME."""
import build


def fake_checkout(tmp_path, monkeypatch, dotgit=None):
    root = tmp_path / "checkout"
    root.mkdir()
    if dotgit is not None:
        (root / ".git").write_text(dotgit, encoding="utf-8")
    monkeypatch.setattr(build, "ROOT", root)
    monkeypatch.delenv("DYNAMICRESUME_HOME", raising=False)
    return root


def test_a_plain_checkout_is_its_own_home(tmp_path, monkeypatch):
    root = fake_checkout(tmp_path, monkeypatch)
    (root / ".git").mkdir()
    assert build.find_home() == root


def test_a_worktree_uses_the_main_checkout(tmp_path, monkeypatch):
    main = tmp_path / "main"
    (main / ".git" / "worktrees" / "wt").mkdir(parents=True)
    fake_checkout(tmp_path, monkeypatch, f"gitdir: {main / '.git' / 'worktrees' / 'wt'}\n")
    assert build.find_home() == main.resolve()


def test_a_relative_gitdir_works(tmp_path, monkeypatch):
    main = tmp_path / "main"
    (main / ".git" / "worktrees" / "wt").mkdir(parents=True)
    fake_checkout(tmp_path, monkeypatch, "gitdir: ../main/.git/worktrees/wt\n")
    assert build.find_home() == main.resolve()


def test_a_submodule_style_gitdir_is_not_a_worktree(tmp_path, monkeypatch):
    root = fake_checkout(tmp_path, monkeypatch, "gitdir: ../.git/modules/thing\n")
    assert build.find_home() == root


def test_the_environment_variable_wins(tmp_path, monkeypatch):
    fake_checkout(tmp_path, monkeypatch, "gitdir: ../main/.git/worktrees/wt\n")
    monkeypatch.setenv("DYNAMICRESUME_HOME", str(tmp_path / "elsewhere"))
    assert build.find_home() == (tmp_path / "elsewhere").resolve()


def test_rel_prefers_the_checkout_then_the_home(tmp_path, monkeypatch):
    root = fake_checkout(tmp_path, monkeypatch)
    monkeypatch.setattr(build, "HOME", tmp_path)
    assert build.rel(root / "build" / "x.pdf") == "build/x.pdf"
    assert build.rel(tmp_path / "applications" / "a" / "x.pdf") == "applications/a/x.pdf"
