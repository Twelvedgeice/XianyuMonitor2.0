from src.services.local_browser import desktop_options, storage_from_snapshot

def test_native_options_do_not_override_identity_or_location():
    assert not {'user_agent', 'permissions', 'geolocation', 'is_mobile'} & desktop_options().keys()

def test_extension_and_native_storage_conversion():
    state = storage_from_snapshot({'cookies': [], 'pageUrl': 'https://www.goofish.com/search', 'storage': {'local': {'example': 'value'}}})
    assert state['origins'][0]['localStorage'] == [{'name': 'example', 'value': 'value'}]
    assert storage_from_snapshot(state) == state
    assert storage_from_snapshot({'pageUrl': 'https://example.com', 'storage': {'local': {'x': 'y'}}})['origins'] == []
