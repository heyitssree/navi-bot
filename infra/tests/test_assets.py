import subprocess

from navi_infra.userdata import ASSETS, render_user_data


def render(**kw):
    args = dict(env_name="prod", region="ap-south-1", bucket="bkt", log_group="/navi/prod/bot", image_param="/navi/prod/image_uri",
                bedrock_model_id="global.anthropic.claude-haiku-5-5")
    args.update(kw)
    return "\n".join(render_user_data(**args))


def test_every_placeholder_is_filled_and_assets_are_embedded():
    text = render()
    assert "__" not in text.replace("__init__", "")
    assert "case \"${1:-}\" in" in text and "ExecStart=/opt/navi/update.sh run" in text and "NAVI_BUCKET=bkt" in text


def test_shell_scripts_are_syntactically_valid():
    for script in (render(), (ASSETS / "update.sh").read_text()):
        r = subprocess.run(["bash", "-n"], input=script, text=True, capture_output=True)
        assert r.returncode == 0, r.stderr


def test_update_script_idles_unless_run_enabled_is_true_and_never_stores_credentials():
    text = (ASSETS / "update.sh").read_text()
    assert 'run_enabled' in text and 'exec sleep infinity' in text and "AWS_ACCESS_KEY" not in text
    assert "ssm get-parameter" in text and "|| echo" in text                    # a missing parameter means 'false', not a crash


def test_service_restarts_and_stops_gracefully():
    text = (ASSETS / "navi.service").read_text()
    assert "Restart=always" in text and "docker stop -t 60 navi" in text and "TimeoutStopSec=90" in text


def test_env_file_holds_no_secrets():
    env_block = render().split("cat > /opt/navi/env", 1)[1].split("\nENV\n", 1)[0]
    for key in ("TOKEN", "KEY", "SECRET", "PASSWORD"):
        assert key not in env_block.upper().replace("IMAGE_PARAM", "").replace("BEDROCK_MODEL_ID", "")
    assert "chmod 600 /opt/navi/env" in render()


def test_repo_root_is_two_levels_above_the_stack_file():
    from navi_infra.stacks import compute_stack

    assert (compute_stack.REPO_ROOT / "navi" / "__main__.py").exists() and (compute_stack.REPO_ROOT / "Dockerfile").exists()
