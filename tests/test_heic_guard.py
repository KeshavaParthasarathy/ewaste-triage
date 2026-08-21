"""
Regression guard for a verified silent-corruption bug.

torchvision 0.28's ImageFolder IMG_EXTENSIONS has no `.heic`, so a folder of iPhone
"High Efficiency" photos loads as an empty dataset with no warning, no error, and no
exception — training then reports numbers for data that was never read. The training
script must say so out loud; this test is what keeps it saying so.
"""
from scripts.train_classifier import warn_about_heic


def test_warns_when_a_heic_file_is_present(tmp_path, capsys):
    cls = tmp_path / "train" / "cls_a"
    cls.mkdir(parents=True)
    (cls / "photo.heic").touch()

    warn_about_heic(tmp_path)

    out = capsys.readouterr().out
    assert "1 .heic file(s) found" in out
    assert "photo.heic" in out


def test_silent_when_no_heic_files(tmp_path, capsys):
    cls = tmp_path / "train" / "cls_a"
    cls.mkdir(parents=True)
    (cls / "photo.jpg").touch()

    warn_about_heic(tmp_path)

    assert capsys.readouterr().out == ""
