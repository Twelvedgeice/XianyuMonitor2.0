from src.services import firefox_profile as module


def test_target_preference_is_present_before_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(module.sys, 'platform', 'win32')
    assert module.prepare_background_rendering('private_3', tmp_path)
    content=(tmp_path/'profile/user.js').read_text(encoding='utf-8')
    assert f'user_pref("{module.OCCLUSION_PREF}", false);' in content
    assert not (tmp_path/'profile/user.js.private3-pending').exists()


def test_other_preferences_preserved_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(module.sys, 'platform', 'win32')
    target=tmp_path/'profile/user.js';target.parent.mkdir()
    original='// 自定义设置\nuser_pref("example.setting", 7);\n'
    target.write_text(original,encoding='utf-8')
    original_bytes=target.read_bytes()
    assert module.prepare_background_rendering('private_3',tmp_path)
    expected=target.read_bytes()
    assert expected.startswith(original_bytes)
    assert not module.prepare_background_rendering('private_3',tmp_path)
    assert target.read_bytes()==expected


def test_last_active_value_controls_override(tmp_path,monkeypatch):
    monkeypatch.setattr(module.sys, 'platform', 'win32')
    target=tmp_path/'profile/user.js';target.parent.mkdir()
    target.write_text(f'user_pref("{module.OCCLUSION_PREF}", false);\n'
                      f'user_pref("{module.OCCLUSION_PREF}", true);\n',encoding='utf-8')
    assert module.prepare_background_rendering('private_3',tmp_path)
    assert not module.prepare_background_rendering('private_3',tmp_path)


def test_other_accounts_untouched(tmp_path,monkeypatch):
    monkeypatch.setattr(module.sys, 'platform', 'win32')
    for account in ('private1','private_2','other'):
        assert not module.prepare_background_rendering(account,tmp_path)
    assert list(tmp_path.iterdir())==[]


def test_other_platforms_untouched(tmp_path,monkeypatch):
    monkeypatch.setattr(module.sys, 'platform', 'linux')
    assert not module.prepare_background_rendering('private_3',tmp_path)
    assert list(tmp_path.iterdir())==[]
