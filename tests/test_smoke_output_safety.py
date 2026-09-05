import os
import shutil
import subprocess
import sys
from pathlib import Path


def test_smoke_test_does_not_overwrite_default_production_checkpoint(tmp_path):
    repo = tmp_path / "repo"
    script_dir = repo / "scripts"
    server_dir = repo / "server"
    model_dir = repo / "models"
    script_dir.mkdir(parents=True)
    server_dir.mkdir()
    model_dir.mkdir()

    source = Path(__file__).parents[1] / "scripts" / "train_classifier.py"
    script = script_dir / "train_classifier.py"
    shutil.copy2(source, script)
    shutil.copy2(Path(__file__).parents[1] / "server" / "imaging.py",
                 server_dir / "imaging.py")

    production_checkpoint = model_dir / "best.pt"
    production_classes = model_dir / "classes.json"
    production_checkpoint.write_bytes(b"production-checkpoint")
    production_classes.write_text('["production-class"]')

    env = os.environ.copy()
    env.update({"LC_ALL": "C", "LANG": "C", "LC_CTYPE": "C"})
    subprocess.run(
        [
            sys.executable,
            str(script),
            "--smoke-test",
            "--epochs",
            "1",
            "--batch-size",
            "96",
        ],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert production_checkpoint.read_bytes() == b"production-checkpoint"
    assert production_classes.read_text() == '["production-class"]'
    assert (model_dir / "smoke-test" / "best.pt").is_file()
    assert (model_dir / "smoke-test" / "classes.json").is_file()
