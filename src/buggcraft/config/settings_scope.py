"""Bind a settings page and its child controls to global values explicitly."""


class GlobalSettingsScope:
    def __init__(self, manager):
        self.manager = manager

    def __getattr__(self, name):
        return getattr(self.manager, name)

    def get_version_setting(self, key, default=None):
        return self.manager.get_setting(key, default)

    def set_version_setting(self, key, value):
        return self.manager.set_setting(key, value)

    def get_version_setting_enable(self):
        return False

    def set_version_setting_enable(self, value):
        return False
